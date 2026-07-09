"""
agent/stocks.py
===============
Fetch live stock quotes from Finnhub (https://finnhub.io).

Tracks a configurable watchlist (default: AAPL, TSLA, NVDA) and returns
current price, daily change, and percent change for each ticker.

ENV VARS
--------
    FINNHUB_KEY      your Finnhub API key (required)
    STOCK_WATCHLIST  optional, comma-separated, e.g. "AAPL,TSLA,NVDA,MSFT"
"""

import os
import requests

FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "").strip()
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"

# default watchlist; override with STOCK_WATCHLIST in .env
DEFAULT_WATCHLIST = ["AAPL", "TSLA", "NVDA"]


def _watchlist():
    raw = os.environ.get("STOCK_WATCHLIST", "").strip()
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    return DEFAULT_WATCHLIST


def fetch_quote(ticker):
    """
    Fetch a single stock quote from Finnhub.

    Returns a dict:
        {
            "ticker": "AAPL",
            "price": 195.32,        # current price
            "change": 2.14,         # absolute change today
            "percent": 1.11,        # percent change today
            "high": 196.0,          # day high
            "low": 192.5,           # day low
            "open": 193.1,          # opening price
            "prev_close": 193.18,   # previous close
            "error": None
        }
    Finnhub /quote fields: c=current, d=change, dp=percent, h=high,
                           l=low, o=open, pc=previous close.
    """
    if not FINNHUB_KEY:
        return {"ticker": ticker, "error": "FINNHUB_KEY not set in .env"}

    try:
        resp = requests.get(
            FINNHUB_QUOTE_URL,
            params={"symbol": ticker, "token": FINNHUB_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        d = resp.json()
        # Finnhub returns c=0 for an unknown ticker
        if d.get("c") in (0, None):
            return {"ticker": ticker, "error": "no data (check ticker symbol)"}
        return {
            "ticker": ticker,
            "price": d.get("c"),
            "change": d.get("d"),
            "percent": d.get("dp"),
            "high": d.get("h"),
            "low": d.get("l"),
            "open": d.get("o"),
            "prev_close": d.get("pc"),
            "error": None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def fetch_watchlist():
    """
    Fetch quotes for every ticker in the watchlist.

    Returns:
        {
            "success": bool,
            "quotes": [ {quote dict}, ... ],
            "error": str or None
        }
    """
    if not FINNHUB_KEY:
        return {"success": False, "quotes": [], "error": "FINNHUB_KEY not set in .env"}

    quotes = [fetch_quote(t) for t in _watchlist()]
    return {"success": True, "quotes": quotes, "error": None}


def stocks_text_summary():
    """Plain-text watchlist summary for Wendy to fold into a briefing."""
    result = fetch_watchlist()
    if not result["success"]:
        return f"Could not fetch stocks: {result['error']}"

    lines = []
    for q in result["quotes"]:
        if q.get("error"):
            lines.append(f"{q['ticker']}: {q['error']}")
        else:
            arrow = "▲" if (q["change"] or 0) >= 0 else "▼"
            lines.append(
                f"{q['ticker']}: ${q['price']:.2f} {arrow} "
                f"{q['change']:+.2f} ({q['percent']:+.2f}%)"
            )
    return "\n".join(lines)


# ---- weekly / monthly performance (via free daily history from Yahoo) -------
# Originally scraped stooq.com's CSV export. As of 2026-07-08, stooq now puts
# every request behind a JS bot-verification page ("This site requires
# JavaScript to verify your browser") — confirmed via the debug log below, not
# just a bad guess. That's a real browser challenge; no set of request headers
# from plain `requests` can get past it, so stooq is no longer usable here.
# Switched to Yahoo Finance's public chart JSON endpoint instead — no API key,
# same free-data spirit, and it's the same endpoint the popular `yfinance`
# library scrapes under the hood, so it's well-trodden and currently working.
_YF_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
}


def _period_changes(ticker):
    """Weekly (~5 trading days) and monthly (~21) % change from Yahoo Finance's
    free chart endpoint — no API key. Returns {'price','week','month'} (values
    may be None if history isn't available)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    try:
        resp = requests.get(
            url,
            headers=_YF_HEADERS,
            params={"range": "2mo", "interval": "1d"},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[stocks] yahoo request failed for {ticker}: {e}")
        return {"price": None, "week": None, "month": None}

    try:
        result = data["chart"]["result"][0]
        closes_raw = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        err = (data.get("chart") or {}).get("error")
        print(f"[stocks] yahoo returned no usable history for {ticker}: {err or data}")
        return {"price": None, "week": None, "month": None}

    closes = [c for c in closes_raw if c is not None]

    if len(closes) < 2:
        print(f"[stocks] yahoo returned too few close prices for {ticker}: {closes_raw}")
        return {"price": None, "week": None, "month": None}

    last = closes[-1]

    def pct(n):
        base = closes[-1 - n] if len(closes) > n else closes[0]
        return (last - base) / base * 100 if base else None

    return {"price": last, "week": pct(5), "month": pct(21)}


def fetch_watchlist_periods():
    """Per-ticker current price + weekly + monthly % change for the watchlist."""
    return {"success": True,
            "stocks": [{"ticker": t, **_period_changes(t)} for t in _watchlist()]}


def stocks_period_summary(period="week"):
    """Plain-text weekly OR monthly watchlist summary for a report/briefing."""
    key = "month" if period == "month" else "week"
    label = "month" if key == "month" else "week"
    lines = []
    for s in fetch_watchlist_periods()["stocks"]:
        val = s.get(key)
        if val is None:
            lines.append(f"{s['ticker']}: {label}ly change unavailable")
        else:
            arrow = "▲" if val >= 0 else "▼"
            price = f"${s['price']:.2f} " if s.get("price") else ""
            lines.append(f"{s['ticker']}: {price}{arrow} {val:+.2f}% (past {label})")
    return "\n".join(lines)