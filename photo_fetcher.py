"""
photo_fetcher.py — licensed, news-related photos for Orange News cards.

Source: Pixabay API (free key, Pixabay Content License — commercial use OK,
no attribution required; we still credit "Pixabay" on the card).
Never uses publisher / OG images (copyright — see Instagram suspension 2026-05).

Query strategy (no extra LLM cost):
  1. keywords from the English original_title (stop-words removed)
  2. category fallback query
  3. None → caller draws the branded gradient

Pixabay rules respected: images are downloaded (no hotlinking), results are
cached on disk for 24 h, ~15–30 requests/day (limit is 100/min).
"""
import hashlib
import json
import os
import re
import time

import requests

API_URL = "https://pixabay.com/api/"
CACHE_DIR = os.path.join("assets", "cache", "pixabay")
CACHE_TTL = 24 * 3600

STOP = set("""a an the and or but of to in on at for from by with as is are was were be been
being it its this that these those will would can could may might says say said
after before over under into about amid as than then new why how what who when where
up down out off more most less least vs via per amid against among during while
first second third year years month week day today report reports""".split())

CATEGORY_QUERY = {
    "finance":  "stock market finance",
    "economy":  "economy business city",
    "stock":    "stock exchange trading",
    "tech":     "technology",
    "ai":       "artificial intelligence technology",
    "crypto":   "bitcoin cryptocurrency",
    "energy":   "oil industry energy",
    "commodity": "gold commodities",
    "mongolia": "mongolia ulaanbaatar",
    "business": "business meeting office",
    "video":    "news studio",
}

ENERGY_HINTS = ("oil", "crude", "gas", "opec", "energy", "brent", "lng", "coal")

# headline concept → visual stock-photo query (stock libraries have concepts, not people)
CONCEPTS = [
    (r"\b(gold|bullion)\b|алт", "gold bars"),
    (r"\b(oil|crude|brent|opec|refiner)", "oil refinery"),
    (r"\b(gas|lng)\b", "natural gas pipeline"),
    (r"\b(copper|iron ore|mining|miner|coal)\b", "mining industry"),
    (r"\b(bitcoin|btc)\b", "bitcoin"),
    (r"\b(ethereum|crypto|blockchain|stablecoin|token)", "cryptocurrency"),
    (r"\b(tesla|ev|electric vehicle|cybercab|robotaxi|byd)\b", "electric car"),
    (r"\b(bond|yield|treasur)", "financial chart"),
    (r"\b(fed|federal reserve|rate cut|rate hike|interest rate|central bank|rbi|ecb|boj)", "central bank"),
    (r"\b(rupee|yen|yuan|dollar|currency|forex|euro)\b", "currency money"),
    (r"\b(stock|shares|equit|s&p|nasdaq|dow|wall street|ipo)", "stock market"),
    (r"\b(bank|barclays|jpmorgan|goldman|hsbc|blackrock|fund|asset manager)", "business skyscraper"),
    (r"\b(inflation|gdp|economy|recession|tariff|trade)", "economy business"),
    (r"\b(ai|artificial intelligence|openai|chatgpt|llm|model|nvidia|chip|semiconductor)", "artificial intelligence"),
    (r"\b(apple|iphone|smartphone|google|microsoft|meta|software|app)\b", "technology smartphone"),
    (r"\b(hack|cyberattack|cybersecurity|cyber security|vulnerab|breach|php|цоорхой)", "cyber security"),
    (r"\b(space|rocket|satellite|spacex)", "rocket launch"),
    (r"\b(airline|aviation|boeing|airbus)", "airplane"),
    (r"\b(real estate|housing|property|mortgage)", "real estate city"),
]


def _keywords(title, max_words=3):
    if not title or not re.search(r"[A-Za-z]", title):
        return ""
    words = re.findall(r"[A-Za-z][A-Za-z\-]+", title)
    kept = [w for w in words if w.lower() not in STOP and len(w) > 2]
    # prefer capitalised (company/place names) + nouns early in the title
    caps = [w for w in kept if w[0].isupper()]
    rest = [w for w in kept if not w[0].isupper()]
    return " ".join((caps + rest)[:max_words])


def concept_queries(post):
    """Visual queries from the English title (or Mongolian text for local news)."""
    text = " ".join([post.get("original_title") or "", post.get("headline") or ""]).lower()
    out = []
    for pat, q in CONCEPTS:
        if re.search(pat, text) and q not in out:
            out.append(q)
    return out[:2]


def resolve_category(post):
    """Refine the broad 'finance' category from the headline's main concept."""
    cat = (post.get("category") or "finance").lower()
    if cat != "finance":
        return cat
    first = (concept_queries(post) or [""])[0]
    if first in ("oil refinery", "natural gas pipeline"):
        return "energy"
    if first in ("gold bars", "mining industry"):
        return "commodity"
    return cat


def _cache_get(query):
    path = os.path.join(CACHE_DIR, hashlib.md5(query.encode()).hexdigest() + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _cache_put(query, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.md5(query.encode()).hexdigest() + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _search(query, key):
    cached = _cache_get(query)
    if cached is not None:
        return cached
    r = requests.get(API_URL, params={
        "key": key, "q": query[:100], "image_type": "photo",
        "orientation": "horizontal", "safesearch": "true",
        "min_width": 1200, "per_page": 20, "order": "popular",
    }, timeout=15)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    _cache_put(query, hits)
    return hits


def fetch_photo(post, used_ids, out_dir="assets/cache/photos"):
    """Return (local_path, credit) or (None, None). used_ids: set, avoids repeats in a day."""
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None, None
    cat = resolve_category(post)
    queries = concept_queries(post)
    queries.append(CATEGORY_QUERY.get(cat, "business news"))
    os.makedirs(out_dir, exist_ok=True)
    for q in queries:
        try:
            hits = _search(q, key)
        except Exception as e:
            print(f"    ⚠️ Pixabay '{q}': {e}")
            continue
        for h in hits:
            if h.get("id") in used_ids:
                continue
            url = h.get("largeImageURL") or h.get("webformatURL")
            if not url:
                continue
            path = os.path.join(out_dir, f"pixabay_{h['id']}.jpg")
            try:
                if not os.path.exists(path):
                    img = requests.get(url, timeout=20)
                    img.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(img.content)
                used_ids.add(h["id"])
                print(f"    📷 Pixabay #{h['id']} ← '{q}'")
                return path, "Pixabay"
            except Exception as e:
                print(f"    ⚠️ download failed #{h.get('id')}: {e}")
    return None, None
