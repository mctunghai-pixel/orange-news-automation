"""
photo_fetcher.py — licensed, news-related photos for Orange News cards.

fix30: stories about a named company / product / person first try Wikimedia
Commons (freely licensed real photos: a Tesla Cybertruck story gets a Cybertruck,
not a random EV). Only CC0 / Public domain / CC BY / CC BY-SA files are used, and
the required credit is written into the post text (post["photo_credit"]).

Source: Pixabay API (free key, Pixabay Content License — commercial use OK,
no attribution required — cards carry only our own logo, no credit chip).
Never uses publisher / OG images (copyright — see Instagram suspension 2026-05).

Query strategy (no extra LLM cost):
  1. keywords from the English original_title (stop-words removed)
  2. category fallback query
  3. None → caller draws the branded gradient

Pixabay rules respected: images are downloaded (no hotlinking), results are
cached on disk for 24 h, ~15–30 requests/day (limit is 100/min).
"""
import glob
import hashlib
import json
import os
import random
import re
import time

import requests

API_URL = "https://pixabay.com/api/"
CACHE_DIR = os.path.join("assets", "cache", "pixabay")
CACHE_TTL = 24 * 3600
HISTORY_DAYS = 21          # a Pixabay photo is not reused within this many days
PICK_FROM = 12             # choose among the top-N unused hits (variety, still relevant)

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
    (r"\b(gold|bullion)\b|(?<![а-яөү])алт(ны|ан|)\b", "gold bars"),
    (r"\b(oil|crude|brent|opec|refiner)|газрын тос|нефть|бензин|шатахуун", "oil refinery"),
    (r"\b(gas|lng)\b", "natural gas pipeline"),
    (r"\b(copper|iron ore|mining|miner|coal)\b|зэс|нүүрс|уул уурхай|төмрийн хүдэр|оюу толгой", "mining industry"),
    (r"\b(bitcoin|btc)\b|биткойн", "bitcoin"),
    (r"\b(ethereum|crypto|blockchain|stablecoin|token)|крипто|блокчэйн", "cryptocurrency"),
    (r"\b(tesla|ev|electric vehicle|cybercab|robotaxi|byd)\b|цахилгаан машин|автомашин", "electric car"),
    (r"\b(bond|yield|treasur)", "financial chart"),
    (r"\b(fed|federal reserve|rate cut|rate hike|interest rate|central bank|rbi|ecb|boj)|төв банк|холбооны нөөц|бодлогын хүү", "central bank"),
    (r"\b(rupee|yen|yuan|dollar|currency|forex|euro)\b|ханш|төгрөг|доллар|юань", "currency money"),
    (r"\b(stock|shares|equit|s&p|nasdaq|dow|wall street|ipo)|хувьцаа|хөрөнгийн бирж|хөрөнгийн зах", "stock market"),
    (r"\b(bank|barclays|jpmorgan|goldman|hsbc|blackrock|fund|asset manager)", "business skyscraper"),
    (r"\b(jobs|payroll|employment|unemployment|hiring|labor|labour|workers)\b|ажлын байр|ажилгүйдэл|хөдөлмөр", "office workers"),
    (r"\b(election|midterm|congress|senate|democrat|republican|vote|white house)|сонгууль|конгресс|цагаан ордон", "capitol washington"),
    (r"\b(war|military|missile|strike|conflict|iran|israel|ukraine)\b|дайн|цэргийн|зөрчилдөөн", "world map globe"),
    (r"\b(spy|espionage|intelligence agency|sanction)", "cyber security"),
    (r"\b(ceo|leadership|executive|chairman|founder)\b", "business leader"),
    (r"\b(china|chinese|beijing)\b", "shanghai skyline"),
    (r"\b(inflation|gdp|economy|recession|tariff|trade)|инфляц|эдийн засаг|худалдаа|тариф", "economy business"),
    (r"\b(ai|artificial intelligence|openai|chatgpt|llm|model|nvidia|chip|semiconductor)|хиймэл оюун|чип", "artificial intelligence"),
    (r"\b(apple|iphone|smartphone|google|microsoft|meta|software|app)\b", "technology smartphone"),
    (r"\b(hack|cyberattack|cybersecurity|cyber security|vulnerab|breach|php|цоорхой)", "cyber security"),
    (r"\b(space|rocket|satellite|spacex)", "rocket launch"),
    (r"\b(airline|aviation|boeing|airbus)", "airplane"),
    (r"\b(real estate|housing|property|mortgage)", "real estate city"),
]


# ---------------------------------------------------------------- fix30: Commons
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_UA = "AravtNewsBot/1.0 (https://www.aravtnews.com; info@aravtnews.com)"
FREE_LICENSES = re.compile(r"^(cc0|public domain|pd\b|cc by(-sa)? \d)", re.I)
BAD_FILE = re.compile(r"logo|map|chart|diagram|graph|icon|flag|coat of arms|screenshot|"
                      r"\.svg|signature|seal|stamp|poster|banner|infographic", re.I)

# headline entity → Commons search. Ordered: most specific first. Matches the
# English original title and the Mongolian headline (Latin names stay Latin).
ENTITIES = [
    (r"cybertruck", "Tesla Cybertruck"),
    (r"cybercab|robotaxi", "Tesla Cybercab"),
    (r"\bmodel (y|3)\b", "Tesla Model Y"),
    (r"\b(elon )?musk\b|илон маск", "Elon Musk"),
    (r"\bspacex\b|starship", "SpaceX Starship"),
    (r"\btesla\b", "Tesla Gigafactory"),
    (r"jensen huang|\bhuang\b", "Jensen Huang"),
    (r"\bnvidia\b", "Nvidia headquarters Santa Clara"),
    (r"sam altman", "Sam Altman"),
    (r"\bopenai\b|chatgpt", "OpenAI office"),
    (r"\btsmc\b", "TSMC fab"),
    (r"\bsamsung\b", "Samsung Electronics building"),
    (r"\bapple\b|iphone|tim cook", "Apple Park"),
    (r"\bmicrosoft\b", "Microsoft Redmond campus"),
    (r"\bgoogle\b|alphabet", "Googleplex"),
    (r"\bamazon\b", "Amazon Spheres"),
    (r"\bmeta\b|zuckerberg", "Meta Platforms headquarters"),
    (r"\bboeing\b", "Boeing 737 MAX"),
    (r"\bairbus\b", "Airbus A350"),
    (r"exxon", "ExxonMobil"),
    (r"\bchevron\b", "Chevron gas station"),
    (r"\bopec\b", "OPEC headquarters Vienna"),
    (r"\bbyd\b", "BYD electric car"),
    (r"\btoyota\b", "Toyota headquarters"),
    (r"warren buffett|berkshire", "Warren Buffett"),
    (r"jamie dimon|jpmorgan", "JPMorgan Chase Tower"),
    (r"goldman sachs", "Goldman Sachs headquarters"),
    (r"blackrock", "BlackRock headquarters"),
    (r"jerome powell|\bpowell\b", "Jerome Powell"),
    (r"federal reserve|\bthe fed\b|\bfed\b|холбооны нөөц", "Marriner S. Eccles Federal Reserve Board Building"),
    (r"\becb\b|lagarde|european central bank", "European Central Bank Frankfurt"),
    (r"bank of japan|\bboj\b", "Bank of Japan headquarters"),
    (r"\btrump\b|трамп", "Donald Trump"),
    (r"white house|цагаан ордон", "White House"),
    (r"wall street|nyse|new york stock exchange", "New York Stock Exchange"),
    (r"nasdaq", "Nasdaq MarketSite Times Square"),
    (r"\bxi jinping\b|си жиньпин", "Xi Jinping"),
    (r"oyu tolgoi|оюу толгой", "Oyu Tolgoi mine"),
    (r"tavan tolgoi|таван толгой", "Tavan Tolgoi"),
    (r"ulaanbaatar|улаанбаатар", "Ulaanbaatar skyline"),
    (r"baltic exchange", "Baltic Exchange London"),
    (r"\bbinance\b", "Binance"),
    (r"coinbase", "Coinbase"),
    (r"vitalik|buterin", "Vitalik Buterin"),
]


def entity_queries(post):
    text = " ".join([post.get("original_title") or "", post.get("headline") or ""]).lower()
    out = []
    for pat, q in ENTITIES:
        if re.search(pat, text) and q not in out:
            out.append(q)
    return out[:2]


def _strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _commons_search(query):
    key = "commons:" + query
    cached = _cache_get(key)
    if cached is not None:
        return cached
    r = requests.get(COMMONS_API, params={
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 15,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
    }, headers={"User-Agent": COMMONS_UA}, timeout=20)
    r.raise_for_status()
    pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    hits = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = _strip_html((meta.get("LicenseShortName") or {}).get("value"))
        w, h = ii.get("width") or 0, ii.get("height") or 1
        title = p.get("title", "")
        if not FREE_LICENSES.match(lic) or BAD_FILE.search(title):
            continue
        if w < 1200 or not (1.15 <= w / h <= 2.4):      # landscape photos only
            continue
        artist = _strip_html((meta.get("Artist") or {}).get("value"))[:60] or "Wikimedia Commons"
        hits.append({"id": f"wm:{p.get('pageid')}", "url": ii.get("thumburl") or ii.get("url"),
                     "license": lic, "artist": artist, "title": title})
    _cache_put(key, hits)
    return hits


def _credit_text(hit):
    lic = hit["license"]
    if re.match(r"cc0|public domain|pd\b", lic, re.I):
        return "📷 Зураг: Wikimedia Commons"
    return f"📷 Зураг: {hit['artist']} / Wikimedia Commons ({lic})"


def fetch_commons(post, used_ids, out_dir):
    for q in entity_queries(post):
        try:
            hits = _commons_search(q)
        except Exception as e:
            print(f"    ⚠️ Commons '{q}': {e}")
            continue
        fresh = [h for h in hits if h["id"] not in used_ids][:6]
        random.Random(post.get("original_title") or post.get("headline") or q).shuffle(fresh)
        for h in fresh:
            path = os.path.join(out_dir, f"commons_{h['id'][3:]}.jpg")
            try:
                if not os.path.exists(path):
                    img = requests.get(h["url"], headers={"User-Agent": COMMONS_UA}, timeout=30)
                    img.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(img.content)
                used_ids.add(h["id"])
                post["photo_id"], post["photo_url"] = h["id"], h["url"]
                post["photo_credit"] = _credit_text(h)
                print(f"    📷 Commons {h['id']} ← '{q}' ({h['license']})")
                return path, "Wikimedia Commons"
            except Exception as e:
                print(f"    ⚠️ Commons download {h['id']}: {e}")
    return None, None


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
    return out[:3]


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


def recent_photo_ids(archive_dir="archive", days=HISTORY_DAYS):
    """Pixabay ids used in the last `days` archive snapshots (+ translated_posts.json)."""
    ids = set()
    files = sorted(glob.glob(os.path.join(archive_dir, "posts_*.json")))[-days:]
    files.append("translated_posts.json")
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        posts = data.get("posts", []) if isinstance(data, dict) else data
        for p in posts or []:
            if isinstance(p, dict) and p.get("photo_id"):
                ids.add(p["photo_id"])
    return ids


def fetch_photo(post, used_ids, out_dir="assets/cache/photos"):
    """Return (local_path, credit) or (None, None).

    used_ids: Pixabay ids to avoid (recent days + this run). The chosen id is
    stored in post["photo_id"] so the archive remembers it for future runs.
    Picks randomly among the top unused hits (seeded by the headline, so a
    re-run of the same story keeps its photo) for day-to-day variety."""
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    os.makedirs(out_dir, exist_ok=True)
    pid = post.get("photo_id")
    if pid and str(pid).startswith("wm:") and post.get("photo_url"):   # fix30: keep a Commons photo
        path = os.path.join(out_dir, f"commons_{str(pid)[3:]}.jpg")
        try:
            if not os.path.exists(path):
                img = requests.get(post["photo_url"], headers={"User-Agent": COMMONS_UA}, timeout=30)
                img.raise_for_status()
                with open(path, "wb") as f:
                    f.write(img.content)
            used_ids.add(pid)
            return path, "Wikimedia Commons"
        except Exception as e:
            print(f"    ⚠️ reuse Commons {pid}: {e}")
        pid = None
    if pid and not str(pid).startswith("wm:"):   # a later run the same day keeps the story's photo (FB/IG/site stay consistent)
        path = os.path.join(out_dir, f"pixabay_{pid}.jpg")
        try:
            if not os.path.exists(path):
                r = requests.get(API_URL, params={"key": key, "id": pid}, timeout=15)
                r.raise_for_status()
                hits = r.json().get("hits", [])
                url = hits and (hits[0].get("largeImageURL") or hits[0].get("webformatURL"))
                if url:
                    img = requests.get(url, timeout=20)
                    img.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(img.content)
            if os.path.exists(path):
                used_ids.add(pid)
                print(f"    📷 Pixabay #{pid} (kept from earlier run)")
                return path, "Pixabay"
        except Exception as e:
            print(f"    ⚠️ reuse photo #{pid}: {e}")
    path, credit = fetch_commons(post, used_ids, out_dir)
    if path:
        return path, credit
    cat = resolve_category(post)
    queries = concept_queries(post)
    queries.append(CATEGORY_QUERY.get(cat, "business news"))
    os.makedirs(out_dir, exist_ok=True)
    if not key:
        return None, None
    for q in queries:
        try:
            hits = _search(q, key)
        except Exception as e:
            print(f"    ⚠️ Pixabay '{q}': {e}")
            continue
        seed = (post.get("original_title") or post.get("headline") or q)
        fresh = [h for h in hits if h.get("id") not in used_ids][:PICK_FROM]
        random.Random(seed).shuffle(fresh)
        for h in fresh:
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
                post["photo_id"] = h["id"]
                print(f"    📷 Pixabay #{h['id']} ← '{q}'")
                return path, "Pixabay"
            except Exception as e:
                print(f"    ⚠️ download failed #{h.get('id')}: {e}")
    return None, None
