"""montsame_scraper.py — Phase 6.1.5

Mongolian-language HTML scraper for montsame.mn. Day 6 recon proved the
Mongolian web doesn't expose RSS broadly (montsame, news.mn, gogo, eagle,
shuud, unen, baabar — all 404 / TCP-unreachable / serve HTML); ikon.mn (RSS)
remains the only verified working RSS source. This adds Montsame via HTML
scraping to give the pipeline a second native-Mongolian source for financial
content.

Returns articles in the same dict shape as orange_rss_collector.fetch_feed():
  {title, summary, url, published, source, category, weight}

Sets category="mongolia" so the translator's process_mongolian_article
passthrough kicks in (see orange_translator.py:1473) — translation is skipped,
only Bloomberg-grade editorial polish is applied.

Categories scraped (numeric IDs from Montsame nav, mapped Day 9 recon):
  - /mn/more/10  Эдийн засаг (Economy) — primary financial content
  - /mn/more/16  Уул уурхай  (Mining)  — commodity-relevant secondary

Article URL pattern: /mn/read/<numeric-id>

Author: Azurise AI Master Architect
Date: May 6, 2026
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

MNT_TZ = ZoneInfo("Asia/Ulaanbaatar")

USER_AGENT = "Mozilla/5.0 (compatible; OrangeNews/1.0; +https://www.orangenews.mn)"
HTTP_TIMEOUT = 10
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 2.0

CATEGORY_URLS = [
    "https://www.montsame.mn/mn/more/10",  # Эдийн засаг (Economy)
    "https://www.montsame.mn/mn/more/16",  # Уул уурхай  (Mining)
]

ARTICLE_HREF_RE = re.compile(r"^/mn/read/\d+$")
BG_IMAGE_RE = re.compile(r"url\(['\"]?(.*?)['\"]?\)")

SOURCE_NAME = "Montsame"
WEIGHT = 1.5  # matches ikon.mn weight in RSS_FEEDS

BODY_CHAR_CAP = 1500          # translator polishes; cap to keep memory tiny
PER_CATEGORY_STUB_CAP = 6     # pull a few extra so dedupe + sort still has variety


# =============================================================================
# HTTP
# =============================================================================

def _http_get(url: str) -> Optional[str]:
    """Fetch URL with retry+backoff. Returns text on success, None on hard fail."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            if r.ok:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            print(f"[montsame] {url}: HTTP {r.status_code} (attempt {attempt}/{RETRY_ATTEMPTS})")
        except requests.RequestException as e:
            print(f"[montsame] {url}: {type(e).__name__}: {e} (attempt {attempt}/{RETRY_ATTEMPTS})")
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SEC * attempt)
    return None


# =============================================================================
# PARSERS
# =============================================================================

def _parse_category_page(html: str) -> list[dict]:
    """Extract article stubs from a category page's <div class='news-box'> blocks."""
    soup = BeautifulSoup(html, "html.parser")
    stubs: list[dict] = []
    for box in soup.select("div.news-box"):
        a = box.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not ARTICLE_HREF_RE.match(href):
            continue

        title_div = a.select_one(".title.content-mn")
        if not title_div:
            continue
        title = title_div.get_text(strip=True)
        if not title:
            continue

        body_div = a.select_one(".body.content-mn")
        excerpt = body_div.get_text(" ", strip=True) if body_div else ""

        image_url = None
        img_div = a.select_one(".news-image-bg")
        if img_div and img_div.get("style"):
            m = BG_IMAGE_RE.search(img_div["style"])
            if m:
                path = m.group(1)
                image_url = path if path.startswith("http") else f"https://www.montsame.mn{path}"

        stubs.append({
            "url":     f"https://www.montsame.mn{href}",
            "title":   title,
            "summary": excerpt,
            "image":   image_url,
        })
    return stubs


def _extract_full_body(article_html: str) -> Optional[str]:
    """Extract the main article body text from a Montsame article page.

    Heuristic: pick the longest text-bearing `.content-mn` block on the page.
    Header chrome / sidebar widgets share the class but carry only short
    snippets, so the longest block is reliably the article body. Falls back
    to og:description if no usable block is found."""
    soup = BeautifulSoup(article_html, "html.parser")

    candidates = soup.select(".content-mn")
    best_text = ""
    for c in candidates:
        text = c.get_text(" ", strip=True)
        if len(text) > len(best_text):
            best_text = text

    if len(best_text) >= 100:
        return best_text

    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        return og_desc["content"].strip()
    return None


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def fetch_articles(limit: int = 3) -> list[dict]:
    """Fetch top `limit` Montsame articles across configured categories.
    Returns dicts in orange_rss_collector.fetch_feed() shape."""
    fetched_at = datetime.now(MNT_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

    raw_stubs: list[dict] = []
    for cat_url in CATEGORY_URLS:
        html = _http_get(cat_url)
        if not html:
            continue
        try:
            stubs = _parse_category_page(html)
        except Exception as e:
            print(f"[montsame] parse error on {cat_url}: {type(e).__name__}: {e}")
            continue
        raw_stubs.extend(stubs[:PER_CATEGORY_STUB_CAP])

    # Dedupe by URL — Economy + Mining sometimes carry the same item
    seen: set[str] = set()
    unique: list[dict] = []
    for s in raw_stubs:
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        unique.append(s)

    out: list[dict] = []
    for stub in unique:
        if len(out) >= limit:
            break
        article_html = _http_get(stub["url"])
        body = None
        if article_html:
            try:
                body = _extract_full_body(article_html)
            except Exception as e:
                print(f"[montsame] body parse error on {stub['url']}: {type(e).__name__}: {e}")
        body = body or stub["summary"]
        if not body:
            continue
        out.append({
            "title":     stub["title"],
            "summary":   body[:BODY_CHAR_CAP],
            "url":       stub["url"],
            "published": fetched_at,  # Montsame article HTML doesn't expose canonical pub time
            "source":    SOURCE_NAME,
            "category":  "mongolia",
            "weight":    WEIGHT,
        })
    return out


# =============================================================================
# CLI (manual smoke test)
# =============================================================================

if __name__ == "__main__":
    items = fetch_articles(limit=3)
    print(f"\n📰 Fetched {len(items)} Montsame article(s):\n")
    for i, it in enumerate(items, 1):
        print(f"  {i}. [{it['source']} | {it['category']} | weight={it['weight']}]")
        print(f"     Title: {it['title']}")
        print(f"     URL:   {it['url']}")
        print(f"     Body:  {len(it['summary'])} chars")
        print(f"     Sample: {it['summary'][:160]}…")
        print()
