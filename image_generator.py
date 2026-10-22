"""
Orange News — Image Generator v9 (Visual Standard v1)
=====================================================
* FB feed card 1080x1350 (4:5): licensed news photo + brand panel  → post_NN_YYYYMMDD.png
* Website card 1200x675 (16:9): photo + logo + category             → web_NN_YYYYMMDD.jpg
* Market Watch: live data card built from market_data.json           → post_00_YYYYMMDD.png
* Photos: Pixabay (photo_fetcher.py). Publisher/OG images are never used (copyright).
* Fallback: branded category gradient when no photo is available.

CLI:
  python3 image_generator.py                    # all posts in translated_posts.json
  python3 image_generator.py --market-watch-only
"""
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from brand_card import news_card, market_watch_card, web_card, gradient_photo
from photo_fetcher import fetch_photo, resolve_category

MNT = ZoneInfo("Asia/Ulaanbaatar")
OUTPUT_DIR = "assets/generated"
LOGO_PATH = "assets/logo.png"
INPUT_FILE = "translated_posts.json"
MARKET_FILE = "market_data.json"

SOURCE_NAMES = [
    (r"bloomberg", "Bloomberg"), (r"reuters", "Reuters"), (r"financial times|ft\.com", "Financial Times"),
    (r"wsj|wall street|dow jones", "WSJ"), (r"cnbc", "CNBC"), (r"techcrunch", "TechCrunch"),
    (r"verge", "The Verge"), (r"ars ?technica", "Ars Technica"), (r"bbc", "BBC"),
    (r"cointelegraph", "Cointelegraph"), (r"decrypt", "Decrypt"), (r"venturebeat", "VentureBeat"),
    (r"ikon", "iKon.mn"), (r"montsame", "Монцамэ"),
]


def today_str(fmt="%Y%m%d"):
    return datetime.now(MNT).strftime(fmt)


def clean_source(src):
    s = (src or "").lower()
    for pat, name in SOURCE_NAMES:
        if re.search(pat, s):
            return name
    return (src or "Orange News").split(" - ")[0].strip()


def clean_headline(text):
    text = re.sub(r"[#*_`]+", "", text or "").strip()
    return re.sub(r"\s+", " ", text)


def is_market_watch(p):
    return bool(p.get("use_market_watch_image") or p.get("type") == "market_watch"
                or p.get("category") == "market_watch" or p.get("is_market_watch"))


def market_rows(md):
    def item(key, label, fmt, show_chg=True):
        v = md.get(key)
        if not v or v.get("price") is None:
            return None
        return (label, fmt.format(v["price"]), v.get("changePct") if show_chg else None)
    sections = [
        ("ХӨРӨНГИЙН ЗАХ ЗЭЭЛ", [item("spx", "S&P 500", "{:,.0f}"), item("ixic", "Nasdaq", "{:,.0f}"),
                                item("dji", "Dow Jones", "{:,.0f}"), item("msetop20", "MSE TOP-20", "{:,.0f}")]),
        ("КРИПТО", [item("btc", "Bitcoin", "${:,.0f}"), item("eth", "Ethereum", "${:,.0f}")]),
        ("ТҮҮХИЙ ЭД", [item("xau", "Алт (унц)", "${:,.0f}"), item("cl", "Газрын тос WTI", "${:,.2f}")]),
        ("ВАЛЮТ", [item("mntusd", "USD / MNT", "{:,.0f}₮", show_chg=False)]),
    ]
    return [(name, [i for i in items if i]) for name, items in sections if any(items)]


def build_market_watch(index=0):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = f"{OUTPUT_DIR}/post_{index:02d}_{today_str()}.png"
    with open(MARKET_FILE, encoding="utf-8") as f:
        rows = market_rows(json.load(f))
    if not rows:
        raise RuntimeError("market_data.json has no usable rows")
    return market_watch_card(rows, today_str("%Y.%m.%d"), LOGO_PATH, out)


def build_news(post, index, used_ids):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cat = resolve_category(post)
    photo, credit = fetch_photo(post, used_ids)
    if not photo:
        print("    🎨 branded gradient (no licensed photo)")
        photo = gradient_photo(cat, f"{OUTPUT_DIR}/_bg_{index:02d}.jpg")
        credit = None
    headline = clean_headline(post.get("headline") or post.get("title", ""))
    feed = f"{OUTPUT_DIR}/post_{index:02d}_{today_str()}.png"
    news_card(photo, headline, cat, clean_source(post.get("source")), today_str("%Y.%m.%d"),
              LOGO_PATH, feed, photo_credit=credit)
    web = f"{OUTPUT_DIR}/web_{index:02d}_{today_str()}.jpg"
    web_card(photo, cat, LOGO_PATH, web)
    return feed, web


def generate_image(headline, category="FINANCE", image_url=None, article_url=None,
                   index=0, image_caption=None):
    """Backward-compatible entry point used by fb_poster.py fallback."""
    if (category or "").lower() == "market_watch":
        return build_market_watch(index)
    post = {"headline": headline, "category": (category or "finance").lower(), "source": ""}
    return build_news(post, index, set())[0]


def main():
    mw_only = "--market-watch-only" in sys.argv
    print("🎨 Orange News Image Generator v9 — Visual Standard v1")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ {INPUT_FILE} not found"); return 1
    with open(INPUT_FILE, encoding="utf-8") as f:
        posts = json.load(f)
    used_ids, ok, failed = set(), 0, 0
    for i, p in enumerate(posts):
        mw = is_market_watch(p)
        if mw_only and not mw:
            continue
        print(f"  [{i:02d}] {'MARKET WATCH' if mw else clean_headline(p.get('headline', ''))[:60]}")
        try:
            if mw:
                p["image_path"] = build_market_watch(i)
            else:
                p["image_path"], p["image_web"] = build_news(p, i, used_ids)
            ok += 1
        except Exception as e:
            print(f"       ❌ {e}")
            failed += 1
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    print(f"✅ {ok} images, ⚠️ {failed} failed → {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
