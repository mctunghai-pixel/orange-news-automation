"""
Orange News — RSS Feed Collector v7 FINAL
==========================================
Бүх засвар нэгтгэсэн эцсийн хувилбар

Шинэчлэлт:
1. ✅ url + link хоёр талбар хоёулаа хадгална (backward compatibility)
2. ✅ SSL certificate зөв тохируулсан
3. ✅ Keyword scoring илүү нарийн болсон
4. ✅ Top 9 мэдээ буцаана (10 пост = 1 Market Watch + 9 news)

Dependencies: pip install feedparser httpx python-dateutil certifi
"""

import os
import certifi
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


# =============================================================================
# RSS FEEDS
# =============================================================================

RSS_FEEDS = [
    # Technology
    {"url": "https://feeds.bbci.co.uk/news/technology/rss.xml",       "category": "tech",    "weight": 1.2},
    {"url": "https://techcrunch.com/feed/",                            "category": "tech",    "weight": 1.3},
    {"url": "https://www.theverge.com/rss/index.xml",                 "category": "tech",    "weight": 1.1},
    {"url": "https://feeds.arstechnica.com/arstechnica/index",        "category": "tech",    "weight": 1.1},
    # Finance / Markets
    {"url": "https://feeds.bloomberg.com/markets/news.rss",           "category": "finance", "weight": 1.4},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "category": "finance", "weight": 1.3},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  "category": "finance", "weight": 1.2},
    # Crypto
    {"url": "https://cointelegraph.com/rss",                          "category": "crypto",  "weight": 1.2},
    {"url": "https://decrypt.co/feed",                                "category": "crypto",  "weight": 1.1},
    # AI
    {"url": "https://venturebeat.com/feed/",                          "category": "AI",      "weight": 1.5},
]

BOOST_KEYWORDS = [
    "AI", "artificial intelligence", "Bitcoin", "crypto", "stock market",
    "Fed", "interest rate", "NVIDIA", "Tesla", "Apple", "Google", "Microsoft",
    "startup", "IPO", "earnings", "recession", "inflation", "GDP",
    "semiconductor", "OpenAI", "ChatGPT", "Gemini", "LLM", "Mongolia",
    "copper", "gold", "oil",
]

PENALTY_KEYWORDS = [
    "sponsored", "advertisement", "subscribe", "cookie", "privacy policy",
    "terms of service", "weekly roundup",
]

# V7: 9 мэдээ буцаана (1 Market Watch + 9 news = 10 пост)
TOP_N = 9


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class NewsItem:
    title: str
    summary: str
    url: str           # Primary URL field
    link: str          # Backward compatibility (translator.py-д)
    published: str
    source: str
    category: str
    score: float


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def fetch_feed(feed_config: dict):
    try:
        parsed = feedparser.parse(feed_config["url"])
        entries = []
        for entry in parsed.entries[:20]:
            entries.append({
                "title":     entry.get("title", "").strip(),
                "summary":   _clean_html(entry.get("summary", entry.get("description", ""))),
                "url":       entry.get("link", ""),
                "published": _normalize_date(entry.get("published", entry.get("updated", ""))),
                "source":    parsed.feed.get("title", feed_config["url"]),
                "category":  feed_config["category"],
                "weight":    feed_config["weight"],
            })
        return entries
    except Exception as e:
        print(f"[WARN] {feed_config['url']}: {e}")
        return []


def score_article(entry: dict) -> float:
    text = (entry["title"] + " " + entry["summary"]).lower()
    score = 3.0

    for kw in BOOST_KEYWORDS:
        if kw.lower() in text:
            score += 0.5

    for kw in PENALTY_KEYWORDS:
        if kw.lower() in text:
            score -= 1.5

    # Recency
    try:
        pub_dt = dateparser.parse(entry["published"])
        if pub_dt:
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
            recency_bonus = max(0, 2.0 - (age_hours / 12) * 2.0)
            score += recency_bonus
    except:
        pass

    # Title quality
    title_len = len(entry["title"])
    if 30 <= title_len <= 100:
        score += 0.3

    score *= entry.get("weight", 1.0)
    return round(min(score, 10.0), 2)


def collect_top_news(top_n: int = TOP_N):
    all_entries = []

    for feed_config in RSS_FEEDS:
        entries = fetch_feed(feed_config)
        all_entries.extend(entries)
        print(f"  ✓ {feed_config['category'].upper():8s} | {len(entries):2d} | {feed_config['url'].split('/')[2]}")

    # Dedupe
    seen_urls = set()
    scored = []
    for entry in all_entries:
        if entry["url"] not in seen_urls and entry["title"]:
            entry["score"] = score_article(entry)
            scored.append(entry)
            seen_urls.add(entry["url"])

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    return [
        NewsItem(
            title=e["title"],
            summary=e["summary"][:300],
            url=e["url"],
            link=e["url"],    # V7: Backward compat — translator.py "link" хайна
            published=e["published"],
            source=e["source"],
            category=e["category"],
            score=e["score"],
        )
        for e in top
    ]


# =============================================================================
# HELPERS
# =============================================================================

def _clean_html(raw: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", clean).strip()


def _normalize_date(raw: str) -> str:
    try:
        dt = dateparser.parse(raw)
        return dt.isoformat() if dt else raw
    except:
        return raw


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("\n🍊 Orange News — RSS Collector v7")
    print("=" * 50)

    articles = collect_top_news()

    print(f"\n📰 TOP {TOP_N} МЭДЭЭ:\n")
    for i, a in enumerate(articles, 1):
        print(f"{i:2d}. [{a.score:.1f}] [{a.category.upper()}] {a.title[:70]}")

    output = [asdict(a) for a in articles]
    with open("top_news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ top_news.json → дараагийн шат (translator) бэлэн")
