"""
agent/briefing.py
=================
The "Daily Briefing" — Wendy gathers news, stock quotes, and weather, then
writes a thoughtful 5–10 minute analysis: what's happening, areas to watch,
and stocks worth a closer look.

The heavy lifting (analysis + writing) is done by Claude via wendy_agent's
client. We gather raw data here, hand it to Claude with a focused prompt,
and cache the result so we only regenerate once per day (default 8 AM).

ENV VARS used indirectly: ANTHROPIC_API_KEY, NEWSAPI_KEY, FINNHUB_KEY.
"""

import os
import json
import datetime

from agent.news import fetch_news
from agent.stocks import fetch_watchlist, stocks_text_summary, stocks_period_summary
from agent.weather import fetch_weather, weather_text_summary
from agent import db


# -- simple on-disk cache so we regenerate at most once per day -----------
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "_briefing_cache.json")

# hour of day (local) the briefing is "for"; used in the cache key
BRIEFING_HOUR = int(os.environ.get("BRIEFING_HOUR", "8"))


def _today_key():
    """Cache key like '2026-06-25' — one briefing per calendar day."""
    return datetime.date.today().isoformat()


def _read_cache():
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(data):
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"briefing cache write failed: {e}")


BRIEFING_PROMPT = """\
You are Wendy Zhou writing the user's Daily Briefing. Using ONLY the data \
provided below (news headlines, stock quotes, and weather), write a clear, \
SCANNABLE briefing — short and punchy, not dense paragraphs. The user should \
be able to skim it in under 2 minutes, not read it like an essay for 10.

Hard formatting rules:
- Each bullet point is 1–2 short sentences MAX. Never a paragraph under a bullet.
- No sentence should try to pack in more than one idea. Split it into two \
bullets instead.
- Use bold only for the single most important word or number per bullet, not \
whole phrases.
- Skip a line between sections. Never stack two dense blocks back to back.

Structure your briefing with these sections (use markdown headers):

## Good morning
1–2 short sentences: today's date, the weather in Waterloo, and the single \
most important thing to know today. No more.

## Markets — your watchlist (this week)
One bullet per stock using the PAST-WEEK move (not the daily move): the weekly % \
change and a single-clause read on what it means. Example style: "**AAPL** +3.1% \
this week — steady climb, no company news behind it." Then add ONE short line on \
the past MONTH across the watchlist (who's up/down over the month). \
End with one line: "*Analysis only — not financial advice.*"

## Stock forecast
One bullet per watchlist ticker: near-term lean (bullish/bearish/mixed) and the \
ONE reason why, in a single clause. Stay grounded in the data given — never \
invent numbers or news. End with one line: "*Short-term read from today's \
data only — not a prediction, not financial advice.*"

## Areas to look into
3–4 bullets max. Each bullet: the theme in bold, then one short clause on why \
it matters. No multi-sentence explanations.

## Stocks to look into
2–3 bullets max. Each: ticker in bold, then one short clause for why it's worth \
a look. End with: "*Do your own research — not financial advice.*"

## Quick weather note
1–2 short sentences. Today's conditions and any heads-up for the next couple days.

Be specific and reference the actual data, but every section should look like a \
tight list, not a wall of text. If data is missing for a section, say so in one \
short line and move on.

=== DATA ===
{data}
=== END DATA ===
"""


def _gather_data():
    """Collect raw news, stocks, and weather into a single text block."""
    parts = []

    # news
    news = fetch_news(days_back=2, max_articles=6)
    if news["success"] and news["articles"]:
        parts.append("NEWS HEADLINES (last 48h):")
        for a in news["articles"][:15]:
            parts.append(f"- {a['title']} ({a['source']}, {a['published_at'][:10]})")
    else:
        parts.append("NEWS: unavailable" + (f" ({news['error']})" if news.get("error") else ""))

    # stocks — weekly + monthly performance (news above stays as-is)
    parts.append("\nSTOCK PERFORMANCE — PAST WEEK (watchlist):")
    parts.append(stocks_period_summary("week"))
    parts.append("\nSTOCK PERFORMANCE — PAST MONTH (watchlist):")
    parts.append(stocks_period_summary("month"))

    # weather
    parts.append("\nWEATHER:")
    parts.append(weather_text_summary())

    return "\n".join(parts)


def generate_briefing(force=False):
    """
    Return today's briefing, generating it via Claude if not already cached.

    Returns: {"date": "...", "briefing": "<markdown>", "generated_at": "...",
              "cached": bool, "error": str|None}
    """
    cache = _read_cache()
    key = _today_key()

    if not force and cache.get("date") == key and cache.get("briefing"):
        return {
            "date": key,
            "briefing": cache["briefing"],
            "generated_at": cache.get("generated_at", ""),
            "cached": True,
            "error": None,
        }

    # need to (re)generate — call Claude
    try:
        from agent.wendy_agent import _get_client, MODEL, WENDY_SYSTEM_PROMPT
        client = _get_client()
        data = _gather_data()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=3000,
            system=WENDY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": BRIEFING_PROMPT.format(data=data)}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        return {"date": key, "briefing": "", "generated_at": "",
                "cached": False, "error": str(e)}

    now = datetime.datetime.now().isoformat(timespec="seconds")
    _write_cache({"date": key, "briefing": text, "generated_at": now})

    # Phase 9 v1: this is a self-run task — nobody asked in chat for this
    # specific regeneration — so log it to the shared activity feed too.
    try:
        db.log_activity("task", "Generated the Daily Briefing (news + stocks + weather)")
    except Exception as e:
        print(f"warning: failed to log briefing activity: {e}")

    return {"date": key, "briefing": text, "generated_at": now,
            "cached": False, "error": None}