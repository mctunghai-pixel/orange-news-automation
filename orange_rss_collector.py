"""
Orange News — RSS Feed Collector & Scorer
Phase 1: Collect → Filter → Score → Return Top 10

Dependencies: pip install feedparser httpx python-dateutil
"""

import os
import certifi
# Fix SSL certificate verification on macOS (Python.org installer)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import ssl
ssl._create_default_https_context = ssl.create_default_context

import feedparser
import json
import re
from datetime import datetime, timezone
from dateutil import parser as dateparser
from dataclasses import dataclass, asdict


# ──────────────────────────────────────────────
# CONFIG: RSS FEEDS (Tech + Finance)
# ──────────────────────────────────────────────
RSS_FEEDS = [
    # Technology
    {"url": "https://feeds.bbci.co.uk/news/technology/rss.xml",       "category": "tech",    "weight": 1.2},
    {"url": "https://techcrunch.com/feed/",                             "category": "tech",    "weight": 1.3},
    {"url": "https://www.theverge.com/rss/index.xml",                  "category": "tech",    "weight": 1.1},
    {"url": "https://feeds.arstechnica.com/arstechnica/index",         "category": "tech",    "weight": 1.1},
    # Finance / Markets
    {"url": "https://feeds.bloomberg.com/markets/news.rss",           "category": "finance", "weight": 1.4},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "category": "finance", "weight": 1.3},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",   "category": "finance", "weight": 1.2},
    # Crypto
    {"url": "https://cointelegraph.com/rss",                           "category": "crypto",  "weight": 1.2},
    {"url": "https://decrypt.co/feed",                                 "category": "crypto",  "weight": 1.1},
    # AI / Emerging Tech
    {"url": "https://venturebeat.com/feed/",                           "category": "AI",      "weight": 1.5},
]

# Keywords that BOOST relevance score
BOOST_KEYWORDS = [
    "AI", "artificial intelligence", "Bitcoin", "crypto", "stock market",
    "Fed", "interest rate", "NVIDIA", "Tesla", "Apple", "Google", "Microsoft",
    "startup", "IPO", "earnings", "recession", "inflation", "GDP",
    "semiconductor", "OpenAI", "ChatGPT", "Gemini", "LLM",
]

# Keywords that LOWER relevance (noise filter)
PENALTY_KEYWORDS = [
    "sponsored", "advertisement", "subscribe", "cookie", "privacy policy",
    "terms of service", "weekly roundup",
]

TOP_N = 10  # Number of top articles to return


# ──────────────────────────────────────────────
# DATA MODEL
# ──────────────────────────────────────────────
@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    published: str        # ISO 8601 string
    source: str
    category: str
    score: float          # Relevance score (0.0 – 10.0)


# ──────────────────────────────────────────────
# CORE FUNCTIONS
# ──────────────────────────────────────────────
def fetch_feed(feed_config: dict) -> list[dict]:
    """Parse a single RSS feed, return list of raw entries."""
    try:
        parsed = feedparser.parse(feed_config["url"])
        entries = []
        for entry in parsed.entries[:20]:  # Take latest 20 per feed
            entries.append({
                "title":    entry.get("title", "").strip(),
                "summary":  _clean_html(entry.get("summary", entry.get("description", ""))),
                "url":      entry.get("link", ""),
                "published": _normalize_date(entry.get("published", entry.get("updated", ""))),
                "source":   parsed.feed.get("title", feed_config["url"]),
                "category": feed_config["category"],
                "weight":   feed_config["weight"],
            })
        return entries
    except Exception as e:
        print(f"[WARN] Failed to fetch {feed_config['url']}: {e}")
        return []


def score_article(entry: dict) -> float:
    """
    Compute relevance score (0–10) based on:
    - Keyword presence in title/summary
    - Recency (fresher = higher)
    - Source weight multiplier
    """
    text = (entry["title"] + " " + entry["summary"]).lower()
    score = 3.0  # Base score

    # Keyword boost
    for kw in BOOST_KEYWORDS:
        if kw.lower() in text:
            score += 0.5

    # Penalty keywords
    for kw in PENALTY_KEYWORDS:
        if kw.lower() in text:
            score -= 1.5

    # Recency boost (max +2.0 for articles < 2h old)
    try:
        pub_dt = dateparser.parse(entry["published"])
        if pub_dt:
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
            recency_bonus = max(0, 2.0 - (age_hours / 12) * 2.0)
            score += recency_bonus
    except Exception:
        pass

    # Title length quality signal (very short or very long titles are lower quality)
    title_len = len(entry["title"])
    if 30 <= title_len <= 100:
        score += 0.3

    # Apply source weight multiplier
    score *= entry.get("weight", 1.0)

    return round(min(score, 10.0), 2)


def collect_top_news(top_n: int = TOP_N) -> list[NewsItem]:
    """
    Main function: fetch all feeds, score each article, return top N.
    
    Usage:
        articles = collect_top_news()
        for a in articles:
            print(a.title, a.score)
    """
    all_entries: list[dict] = []

    for feed_config in RSS_FEEDS:
        entries = fetch_feed(feed_config)
        all_entries.extend(entries)
        print(f"  ✓ {feed_config['category'].upper():8s} | {len(entries):2d} articles | {feed_config['url'].split('/')[2]}")

    # Score and deduplicate by URL
    seen_urls: set[str] = set()
    scored: list[dict] = []
    for entry in all_entries:
        if entry["url"] not in seen_urls and entry["title"]:
            entry["score"] = score_article(entry)
            scored.append(entry)
            seen_urls.add(entry["url"])

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    return [
        NewsItem(
            title=e["title"],
            summary=e["summary"][:300],  # Truncate summary for prompt
            url=e["url"],
            published=e["published"],
            source=e["source"],
            category=e["category"],
            score=e["score"],
        )
        for e in top
    ]


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def _clean_html(raw: str) -> str:
    """Strip HTML tags from summary text."""
    clean = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", clean).strip()


def _normalize_date(raw: str) -> str:
    """Normalize any date string to ISO 8601."""
    try:
        dt = dateparser.parse(raw)
        return dt.isoformat() if dt else raw
    except Exception:
        return raw


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🍊 Orange News — RSS Collector")
    print("=" * 50)

    articles = collect_top_news()

    print(f"\n📰 TOP {TOP_N} ARTICLES:\n")
    for i, a in enumerate(articles, 1):
        print(f"{i:2d}. [{a.score:.1f}] [{a.category.upper()}] {a.title}")
        print(f"     Source : {a.source}")
        print(f"     URL    : {a.url}")
        print()

    # Export to JSON for next pipeline step (Claude translation)
    output = [asdict(a) for a in articles]
    with open("top_news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ Saved to top_news.json → ready for Claude translation step")
