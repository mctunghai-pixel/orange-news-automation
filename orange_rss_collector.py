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
    # Finance / Markets (premium)
    {"url": "https://feeds.bloomberg.com/markets/news.rss",           "category": "finance", "weight": 1.4},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "category": "finance", "weight": 1.3},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  "category": "finance", "weight": 1.2},
    {"url": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best", "category": "finance", "weight": 1.4},
    {"url": "https://www.ft.com/markets?format=rss",                  "category": "finance", "weight": 1.4},
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",          "category": "finance", "weight": 1.4},
    # Crypto
    {"url": "https://cointelegraph.com/rss",                          "category": "crypto",  "weight": 1.2},
    {"url": "https://decrypt.co/feed",                                "category": "crypto",  "weight": 1.1},
    # AI
    {"url": "https://venturebeat.com/feed/",                          "category": "AI",      "weight": 1.5},
    # Mongolia (native-language sources — bypass translator via passthrough path)
    {"url": "https://ikon.mn/rss",                                    "category": "mongolia", "weight": 1.5},
]

# Feed-level category values that mark the source as native Mongolian.
# Matches the passthrough branch in orange_translator.translate_article().
MONGOLIA_FEED_CATEGORY = "mongolia"

# Domains whose articles auto-classify to topic="mongolia" regardless of keyword
# match. Phase 6.1 ships ikon.mn only; Phase 6.1.5 will extend to Montsame +
# news.mn via scrapers.
MONGOLIA_DOMAINS = ["ikon.mn"]

# feedparser default UA is blocked by several .mn sites. Identify cleanly so
# the source can rate-limit / contact us if needed.
FEEDPARSER_UA = "Mozilla/5.0 (compatible; OrangeNews/1.0; +https://www.orangenews.mn)"

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

# =============================================================================
# TOPIC CLASSIFICATION (v8) — quota enforcement
# =============================================================================
# Five priority buckets (1 article each) + "other" (fill remaining slots).
# Keyword matching uses \bword\b (case-insensitive) to avoid false matches
# like "Fed" in "feed" or "AI" in "said".
# =============================================================================

TOPIC_KEYWORDS = {
    "stock":    ["earnings", "revenue", "shares", "stock", "IPO", "S&P", "Nasdaq", "Dow"],
    "macro":    ["Fed", "inflation", "GDP", "unemployment", "recession", "central bank", "interest rate"],
    "ai_tech":  ["AI", "artificial intelligence", "LLM", "OpenAI", "Anthropic", "GPT", "Claude", "Gemini"],
    "crypto":   ["Bitcoin", "BTC", "Ethereum", "ETH", "crypto", "stablecoin", "blockchain"],
    "mongolia": [
        "Mongolia", "Ulaanbaatar", "MNT", "tugrik", "Oyu Tolgoi", "Rio Tinto Mongolia",
        "Монгол", "Улаанбаатар", "төгрөг", "уурхай", "Оюутолгой", "ХХК",
        "банк", "хөрөнгө оруулалт",
    ],
}

# Priority order used when picking quota slots and walking fallbacks.
TOPIC_PRIORITY = ["stock", "macro", "ai_tech", "crypto", "mongolia"]

# Per-topic article count. Mongolia gets 2 to emphasise domestic coverage —
# total priority slots = 6, leaving 3 for "other" at TOP_N = 9.
TOPIC_QUOTA = {
    "stock":    1,
    "macro":    1,
    "ai_tech":  1,
    "crypto":   1,
    "mongolia": 2,
}

# If a topic bucket can't fill its quota, borrow from neighbor buckets in this order.
TOPIC_NEIGHBOR_FALLBACK = {
    "stock":    ["macro", "other"],
    "macro":    ["stock", "other"],
    "ai_tech":  ["other"],
    "crypto":   ["other"],
    "mongolia": ["other"],
}

# V7: 9 мэдээ буцаана (1 Market Watch + 9 news = 10 пост)
TOP_N = 9

# Phase 6.1.6c: extra "other" candidates beyond TOP_N. The translator caps
# successful outputs at TOP_N — spillover only gets translated when earlier
# candidates are dropped (e.g. mongolia coarse/gate rejections). Steady-state
# cost impact: $0 (untranslated). Worst-case (3 drops): +$0.03/day.
SPILLOVER_N = 3


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
    category: str      # Feed-level (tech/finance/crypto/AI)
    topic: str         # v8: article-level (stock/macro/ai_tech/crypto/mongolia/other)
    score: float


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def fetch_feed(feed_config: dict):
    try:
        parsed = feedparser.parse(feed_config["url"], agent=FEEDPARSER_UA)
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


# =============================================================================
# TOPIC CLASSIFIER (v8)
# =============================================================================

# Pre-compile per-topic regex (word boundaries, case-insensitive).
_TOPIC_PATTERNS = {
    topic: re.compile(
        r"\b(" + "|".join(re.escape(kw) for kw in kws) + r")\b",
        re.IGNORECASE,
    )
    for topic, kws in TOPIC_KEYWORDS.items()
}


def classify_topic(entry: dict) -> str:
    """
    Assign an article to exactly one topic bucket.
    Priority order: stock → macro → ai_tech → crypto → mongolia → other.
    First match wins (by priority, not by keyword position).

    Domain shortcut: any article whose URL host matches MONGOLIA_DOMAINS
    auto-classifies as "mongolia" (e.g. ikon.mn). This sidesteps keyword
    misses on Mongolian-language content.
    """
    url = entry.get("url", "") or ""
    if any(d in url for d in MONGOLIA_DOMAINS):
        return "mongolia"
    text = (entry.get("title", "") or "") + " " + (entry.get("summary", "") or "")
    for topic in TOPIC_PRIORITY:
        if _TOPIC_PATTERNS[topic].search(text):
            return topic
    return "other"


# =============================================================================
# QUOTA-ENFORCED SELECTION (v8)
# =============================================================================

def _select_from_neighbor(buckets: dict, selected_urls: set, primary_topic: str):
    """
    When a primary topic bucket is empty, borrow the top-scored article
    from its neighbor fallback list (defined in TOPIC_NEIGHBOR_FALLBACK).
    Returns the entry (with original topic intact) or None if all neighbors empty.
    """
    for neighbor in TOPIC_NEIGHBOR_FALLBACK.get(primary_topic, ["other"]):
        for entry in buckets.get(neighbor, []):
            if entry["url"] not in selected_urls:
                return entry
    return None


def _select_top_news_quota(scored_entries: list, top_n: int = TOP_N):
    """
    Quota-based selection (counts per TOPIC_QUOTA — Phase 6.1: mongolia=2):
      - stock=1, macro=1, ai_tech=1, crypto=1, mongolia=2 (6 priority slots)
      - Remaining slots filled by top-scored 'other' articles
    Returns (ordered_list_of_entries, breakdown_dict) where breakdown_dict tracks
    classification counts and fallback events for logging.
    """
    # Group pre-scored entries by topic, each bucket sorted by score desc.
    buckets = {topic: [] for topic in TOPIC_PRIORITY + ["other"]}
    for entry in scored_entries:
        buckets[entry["topic"]].append(entry)
    for topic in buckets:
        buckets[topic].sort(key=lambda x: x["score"], reverse=True)

    classification_counts = {topic: len(buckets[topic]) for topic in buckets}

    selected = []
    selected_urls = set()
    fallback_notes = []  # (slot, source_topic)

    # Priority pass: TOPIC_QUOTA[topic] articles per priority topic.
    for topic in TOPIC_PRIORITY:
        quota = TOPIC_QUOTA.get(topic, 1)
        filled = 0
        # Drain primary bucket first, up to quota
        for entry in buckets[topic]:
            if filled >= quota:
                break
            if entry["url"] not in selected_urls:
                selected.append(entry)
                selected_urls.add(entry["url"])
                filled += 1
        # Walk neighbor fallbacks for any unfilled slots
        while filled < quota:
            picked = _select_from_neighbor(buckets, selected_urls, topic)
            if picked is None:
                break
            selected.append(picked)
            selected_urls.add(picked["url"])
            fallback_notes.append((topic, picked["topic"]))
            filled += 1

    # Fill remaining slots from 'other' (top-scored first), then any unused.
    remaining = top_n - len(selected)
    if remaining > 0:
        # Prefer 'other' bucket
        for entry in buckets["other"]:
            if len(selected) >= top_n:
                break
            if entry["url"] not in selected_urls:
                selected.append(entry)
                selected_urls.add(entry["url"])
        # If still short, pull from all other buckets by overall score
        if len(selected) < top_n:
            pool = [e for e in scored_entries if e["url"] not in selected_urls]
            pool.sort(key=lambda x: x["score"], reverse=True)
            for entry in pool:
                if len(selected) >= top_n:
                    break
                selected.append(entry)
                selected_urls.add(entry["url"])

    breakdown = {
        "classification_counts": classification_counts,
        "selected_count":        len(selected),
        "fallback_notes":        fallback_notes,
    }
    return selected, breakdown


def collect_top_news(top_n: int = TOP_N):
    """
    v8 pipeline:
      1. Fetch all feeds
      2. Dedupe by URL
      3. Score each article (recency + keyword boost/penalty)
      4. Classify topic (stock/macro/ai_tech/crypto/mongolia/other)
      5. Apply quota selection (1 per priority topic + fill from 'other')
    Returns list of NewsItem + breakdown dict for logging.
    """
    all_entries = []
    for feed_config in RSS_FEEDS:
        entries = fetch_feed(feed_config)
        all_entries.extend(entries)
        print(f"  ✓ {feed_config['category'].upper():8s} | {len(entries):2d} | {feed_config['url'].split('/')[2]}")

    # Dedupe + score + classify
    seen_urls = set()
    scored = []
    for entry in all_entries:
        if entry["url"] not in seen_urls and entry["title"]:
            entry["score"] = score_article(entry)
            entry["topic"] = classify_topic(entry)
            scored.append(entry)
            seen_urls.add(entry["url"])

    # Pull TOP_N + SPILLOVER_N candidates so the translator can backfill
    # rejected articles without dropping below TOP_N successful outputs.
    selected, breakdown = _select_top_news_quota(scored, top_n=top_n + SPILLOVER_N)

    items = [
        NewsItem(
            title=e["title"],
            summary=e["summary"][:300],
            url=e["url"],
            link=e["url"],
            published=e["published"],
            source=e["source"],
            category=e["category"],
            topic=e["topic"],
            score=e["score"],
        )
        for e in selected
    ]
    return items, breakdown


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

def _print_topic_breakdown(articles, breakdown):
    """Print quota-enforcement summary per spec 4.3."""
    counts = breakdown["classification_counts"]
    selected_counts = {}
    for a in articles:
        selected_counts[a.topic] = selected_counts.get(a.topic, 0) + 1

    # Map primary-slot fill to readable note
    note_map = {}
    for slot, source_topic in breakdown["fallback_notes"]:
        note_map[slot] = source_topic

    print("\n📊 Topic breakdown (classified pool → selected):")
    for topic in TOPIC_PRIORITY:
        sel = selected_counts.get(topic, 0)
        pool = counts.get(topic, 0)
        note = ""
        if topic in note_map:
            note = f"  (slot filled from '{note_map[topic]}')"
        print(f"  {topic:9s} pool={pool:2d}  selected={sel}{note}")
    other_sel = selected_counts.get("other", 0)
    other_pool = counts.get("other", 0)
    print(f"  {'other':9s} pool={other_pool:2d}  selected={other_sel}")


if __name__ == "__main__":
    print("\n🍊 Orange News — RSS Collector v8 (quota-enforced)")
    print("=" * 50)

    articles, breakdown = collect_top_news()

    print(f"\n📰 TOP {TOP_N} МЭДЭЭ:\n")
    for i, a in enumerate(articles, 1):
        print(f"{i:2d}. [{a.score:.1f}] [{a.category.upper():8s}|{a.topic:9s}] {a.title[:60]}")

    _print_topic_breakdown(articles, breakdown)

    output = [asdict(a) for a in articles]
    with open("top_news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ top_news.json → дараагийн шат (translator) бэлэн")
