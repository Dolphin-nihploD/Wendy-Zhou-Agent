"""
agent/news.py
=============
Fetch and summarize news from NewsAPI.

This module pulls top articles from NewsAPI.org based on keywords
(tech, engineering, finance, markets) and can provide daily/weekly
briefings to the user.
"""

import os
import requests
from datetime import datetime, timedelta

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_TOPHEADLINES_URL = "https://newsapi.org/v2/top-headlines"

def fetch_news(keywords=None, days_back=7, language="en", max_articles=10):
    """
    Fetch news articles matching keywords from the last N days.

    Args:
        keywords: list of search terms (e.g., ["technology", "artificial intelligence", "stock market"])
                 if None, defaults to ["technology", "artificial intelligence", "stock market"]
        days_back: how many days to search (default 7 for weekly digest)
        language: 'en' for English
        max_articles: max number of articles to return per keyword

    Returns:
        {
            "success": bool,
            "articles": [
                {
                    "title": str,
                    "source": str,
                    "url": str,
                    "description": str,
                    "published_at": str (ISO format),
                    "image_url": str or None
                },
                ...
            ],
            "error": str or None
        }
    """
    if not NEWSAPI_KEY:
        return {
            "success": False,
            "articles": [],
            "error": "NEWSAPI_KEY not set in .env"
        }

    keywords = keywords or ["technology", "artificial intelligence", "stock market"]

    # date range
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days_back)

    articles = []

    for keyword in keywords:
        try:
            params = {
                "q": keyword,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "language": language,
                "sortBy": "publishedAt",
                "pageSize": max_articles,
                "apiKey": NEWSAPI_KEY
            }
            resp = requests.get(NEWSAPI_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    articles.append({
                        "title": article.get("title", ""),
                        "source": article.get("source", {}).get("name", "Unknown"),
                        "url": article.get("url", ""),
                        "description": article.get("description", ""),
                        "published_at": article.get("publishedAt", ""),
                        "image_url": article.get("urlToImage"),
                    })
        except Exception as e:
            print(f"Error fetching news for '{keyword}': {e}")

    # deduplicate by URL, keep first occurrence
    seen = set()
    unique = []
    for article in articles:
        url = article["url"]
        if url not in seen:
            seen.add(url)
            unique.append(article)

    return {
        "success": True,
        "articles": unique[:max_articles * len(keywords)],
        "error": None
    }


def get_news_briefing(days_back=7):
    """
    Get a human-readable news briefing for the past N days.
    Returns a markdown-formatted string suitable for Wendy to include in a reply.
    """
    result = fetch_news(days_back=days_back, max_articles=5)

    if not result["success"]:
        return f"Could not fetch news: {result['error']}"

    articles = result["articles"]
    if not articles:
        return "No recent news found."

    lines = [f"## News from the last {days_back} days\n"]

    for i, article in enumerate(articles[:10], 1):
        title = article["title"]
        source = article["source"]
        url = article["url"]
        pub_date = article["published_at"][:10] if article["published_at"] else "?"

        lines.append(f"{i}. **{title}**")
        lines.append(f"   - {source}, {pub_date}")
        lines.append(f"   - [{url}]({url})\n")

    return "\n".join(lines)
