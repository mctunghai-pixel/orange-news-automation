"""
Orange News — Translator v8 (Gemini primary, Claude fallback)
=============================================================

Major changes from v7:
- Primary: Gemini 2.0 Flash (free tier, better Mongolian output)
- Fallback: Claude Haiku 4.5 (on Gemini failure)
- Startup probe caches working Gemini model for the run
- Full per-article logging → logs/translation_YYYYMMDD_HHMM.json
- Validation layer: headline length, concatenation errors, source tag,
  banned phrases
- Preserved: output schema, Market Watch generator, footer builder, helpers

Author: Azurise AI Master Architect
Date: 2026-04-23
"""

import os
import sys
import json
import time
import re
import certifi
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

MNT_TZ = ZoneInfo("Asia/Ulaanbaatar")

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Local dev: load .env if present. Production (GitHub Actions) uses real env vars
# and ignores this silently when the dotenv package is absent.
# override=True: .env wins over stale shell-exported vars locally. Safe in CI
# because no .env file exists there (gitignored), so load_dotenv is a no-op.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

import httpx as _httpx
import anthropic

try:
    from google import genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    _GENAI_AVAILABLE = False

# =============================================================================
# CONFIG
# =============================================================================

INPUT_FILE  = "top_news.json"
OUTPUT_FILE = "translated_posts.json"
LOG_DIR     = Path("logs")

# Gemini primary (google-genai SDK)
GEMINI_MODEL_PRIMARY   = "gemini-2.0-flash"
GEMINI_MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-1.5-flash"]
ACTIVE_GEMINI_MODEL    = None  # set by get_working_gemini_model()
_GEMINI_CLIENT         = None  # genai.Client instance, set at probe time

# Claude fallback
CLAUDE_MODEL         = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS    = 2500
COST_PER_CLAUDE_USD  = 0.015

# Validation
BANNED_PHRASES        = ["аж ахуйн нэгж"]
CAMELCASE_CYRILLIC_RE = re.compile(r"[А-ЯӨҮ][а-яөү]+[А-ЯӨҮ][а-яөү]+")
SOURCE_TAG_RE         = re.compile(r"Эх сурвалж\s*[:：]")

# Claude client (kept for fallback)
claude_client = anthropic.Anthropic(
    http_client=_httpx.Client(verify=certifi.where())
)

# =============================================================================
# КАТЕГОРИ (7 төрөл) — unchanged
# =============================================================================

CATEGORIES = {
    "finance": {
        "badge": "🔶 FINANCE",
        "hashtags": ["#Finance", "#MarketWatch"],
    },
    "tech": {
        "badge": "🔷 TECH",
        "hashtags": ["#Tech", "#Innovation"],
    },
    "crypto": {
        "badge": "🟡 CRYPTO",
        "hashtags": ["#Crypto", "#Blockchain"],
    },
    "AI": {
        "badge": "🟣 AI",
        "hashtags": ["#AI", "#ArtificialIntelligence"],
    },
    "business": {
        "badge": "🟠 BUSINESS",
        "hashtags": ["#Business", "#Markets"],
    },
    "economy": {
        "badge": "🟢 ECONOMY",
        "hashtags": ["#Economy", "#GlobalMarkets"],
    },
    "mongolia": {
        "badge": "🇲🇳 МОНГОЛ",
        "hashtags": ["#Mongolia", "#Монгол"],
    },
    "market_watch": {
        "badge": "📊 ORANGE MARKET WATCH",
        "hashtags": ["#Finance", "#MarketWatch", "#DailyMarket"],
    }
}

DEFAULT_CATEGORY = "business"

# =============================================================================
# FOOTER (full_post-д оруулна) — v8 Bloomberg-style with visual separators
# =============================================================================

FOOTER_LINKS = """

━━━━━━━━━━━━━━━━━━━━━━

🌐 www.orangenews.mn

📘 facebook.com/orangenews.mn

📷 instagram.com/orangenews.official

🧵 threads.net/@orangenews.official"""


# =============================================================================
# MONGOLIAN_EDITOR_SYSTEM_PROMPT
# =============================================================================
# Role + 7 critical rules + 6 few-shot examples.
# Used by BOTH Gemini (system_instruction) and Claude (system=).
# =============================================================================

MONGOLIAN_EDITOR_SYSTEM_PROMPT = """You are the senior editor of Orange News — a professional Mongolian financial news publication modeled after Bloomberg, Reuters, and Financial Times. You rewrite English financial news into clear, professional Mongolian suitable for the Mongolian investor and business reader.

# 7 CRITICAL RULES

## Rule 1 — NEVER translate literally
Rewrite sentences in natural Mongolian sentence structure. Preserve meaning, discard English syntax.
  WRONG:   "Аж ахуйн нэгжүүдийн 72 хувь нь AI удирдлагыг хуурамчаар тооцож байна"
  CORRECT: "Байгууллагуудын 72% нь AI-ийн хяналт, аюулгүй байдлын эрсдэлийг дутуу үнэлж байна"

## Rule 2 — Foreign-name handling (TIERED — do NOT transliterate everything)

### Category A — Keep in LATIN script (NEVER transliterate)
Corporate brands, tech terms, tickers, crypto symbols:
  Google, AWS, Amazon, Microsoft, Apple, Nvidia, NVIDIA, Tesla, Meta,
  OpenAI, Anthropic, ChatGPT, Claude, Gemini, Rio Tinto
  AI, API, SDK, LLM, GPU, CPU, ETF, IPO, M&A, GDP
  AAPL, NVDA, BTC, ETH, SPY, SOL
  Cloud computing, Data center, AI agent (mixed Latin+Cyrillic OK)

Case endings use hyphen: "Google-ийн", "AWS-ийн", "Nvidia-ын", "Microsoft-ын".

### Category B — TRANSLITERATE to Cyrillic
Political figures, countries, currencies in running text:
  Trump → Трамп, Biden → Байден, Xi Jinping → Ши Жиньпин
  Iran → Иран, China → Хятад, Russia → Орос, Tehran → Тегеран
  dollar → доллар, yen → иен   (but "$" and "USD" stay as-is)
  Fed / Federal Reserve → АНУ-ын Холбооны нөөцийн банк
  Wall Street → Уолл Стрит
  Bitcoin → Биткойн, Ethereum → Этериум   (when used as noun; BTC/ETH as ticker stays Latin)

### Category C — International form / mixed
  "Cloud computing" stays Latin (NOT "Клауд тооцоолол")
  "AI agent" → "AI агент" (mixed is standard for Mongolian tech press)
  "Data center" → "Data center" or "дата төв" (both acceptable)

### Concatenation rule (absolute)
Always add a SPACE between separate proper nouns. NEVER concatenate.
  WRONG:   "ТрампИран", "ТрампИрантай"
  CORRECT: "Трамп Ираны", "Трамп Ирантай"

### Examples
  WRONG:   "Гүүгл, AWS компаниуд AI агентын удирдлага зарлав"
  CORRECT: "Google болон AWS компаниуд AI агентын удирдлага зарлав"
  WRONG:   "Майкрософт OpenAI-д хөрөнгө оруулав"
  CORRECT: "Microsoft OpenAI-д хөрөнгө оруулав"
  WRONG:   "Амазон, Нвидиа түншлэл зарлав"
  CORRECT: "Amazon, Nvidia түншлэл зарлав"

## Rule 3 — Headline style (60-80 characters)
- Professional financial-journalism voice.
- Strong action verbs in past tense: зарлалаа, өсөв, буурав, хүрэв, танилцуулав, санхүүжилт татлаа.
- Include the specific number, ticker, or concrete fact when relevant.
  WRONG:   "Apple компани орлогоо зарлалаа"
  CORRECT: "Apple эхний улиралд 15.3%-ийн орлогын өсөлт зарлав"

## Rule 4 — Preferred terminology
  USE:   компани, байгууллага, зах зээл, хөрөнгө оруулалт, санхүүжилт,
         орлого, ашиг, хувьцаа, улирал, арилжаа, индекс, ханш
  AVOID: аж ахуйн нэгж, аж ахуйн нэгжүүд   (bureaucratic, forbidden)
  Distinguish: орлого (revenue) ≠ ашиг (profit). Do not confuse.

## Rule 5 — Preserve exactly
Do NOT translate or alter these tokens:
- Numbers:      $87,000 stays $87,000
- Percentages:  15.3% stays 15.3%
- Brand names in Latin when they are the subject/entity: NVIDIA, Apple, Microsoft
- Tickers:      AAPL, NVDA, BTC, ETH

## Rule 6 — Past tense for completed events
Use -лаа, -лээ, -лов, -ов for events that have already occurred.
  WRONG:   "ChatGPT загвар зохионо"
  CORRECT: "ChatGPT загвар гарлаа"  OR  "ChatGPT загвар танилцуулав"

## Rule 7 — Source attribution
The body MUST end with exactly this line:
  Эх сурвалж: <source_name>

# 6 FEW-SHOT EXAMPLES

EXAMPLE 1 (AI / Tech):
ENGLISH INPUT: "Anthropic launches Claude 4.7 with a 1M-token context window, tripling prior limits for enterprise coding workflows."
WRONG MONGOLIAN: "Антропик ААН нь 1 сая токентой Клауд 4.7 загвараа гаргасан байгаа нь тогтоогдов."
CORRECT MONGOLIAN: "Антропик компани аж ахуйн кодчилолд зориулсан 1 сая токены контекст цонхтой Claude 4.7 загвараа танилцуулав. Шинэ хязгаар нь өмнөх хувилбараасаа гурав дахин өргөн болжээ."
WHY: Uses "компани" (not "ААН"/"аж ахуйн нэгж"), active past tense (танилцуулав), no passive (байгаа нь тогтоогдов), preserves model name in Latin.

EXAMPLE 2 (Stock market):
ENGLISH INPUT: "Apple reported Q1 earnings of $124.3B, up 15.3% year-over-year; shares rose 4% in after-hours trading."
WRONG MONGOLIAN: "Эпл компани эхний улирлын $124.3 тэрбум орлоготой, жилийн өмнөхөөс 15.3%-ийн өсөлттэй гарч, after-hours trading-т 4%-иар өссөн байна."
CORRECT MONGOLIAN: "Apple эхний улирлын орлогоо 124.3 тэрбум долларт хүргэж, өнгөрсөн оны мөн үеэс 15.3%-иар өслөө. Хувьцаа ажлын цагийн дараах арилжаанд 4%-иар өсөв."
WHY: Apple preserved as Latin brand, active voice throughout, past tense (хүргэж / өслөө / өсөв), uses хувьцаа + арилжаа instead of transliterated English.

EXAMPLE 3 (Macro economy):
ENGLISH INPUT: "The Federal Reserve held rates at 4.25-4.5%, signalling two cuts in 2026 as inflation cooled to 2.4%."
WRONG MONGOLIAN: "Холбооны нөөцийн банк хүүг 4.25-4.5%-д хадгалсан байна. Инфляци 2.4%-д хүрч хөрсөн нь мэдэгдэв."
CORRECT MONGOLIAN: "АНУ-ын Холбооны нөөцийн банк бодлогын хүүг 4.25-4.5%-д хэвээр үлдээв. Инфляци 2.4%-д буурсны дараа 2026 онд хоёр удаа хүү бууруулахаа дохилоо."
WHY: Full Fed naming (АНУ-ын Холбооны нөөцийн банк), active voice, past tense, "дохилоо" captures the signalling nuance naturally.

EXAMPLE 4 (Crypto):
ENGLISH INPUT: "Bitcoin surged past $110,000 for the first time, driven by ETF inflows of $1.2B in a single day."
WRONG MONGOLIAN: "Биткойн анх удаа $110,000-ийг давсан байгаа нь тогтоогдов, ETF-д 1.2 тэрбум долларын орлого орсон байна."
CORRECT MONGOLIAN: "Биткойн анх удаа 110,000 долларын босгыг давж түүхэн дээд амжилт тогтоов. Өдрийн дотор ETF-д 1.2 тэрбум долларын цэвэр хөрөнгө оруулалт орсон нь үнийн өсөлтийг түлхэв."
WHY: Bitcoin transliterated (Биткойн), active voice, past tense, preserves $ and the exact number, no passive "байгаа нь тогтоогдов".

EXAMPLE 5 (Geopolitics affecting markets — CRITICAL concatenation rule):
ENGLISH INPUT: "Trump threatened new 25% tariffs on Iranian oil imports, escalating tensions with Tehran and rattling energy markets."
WRONG MONGOLIAN: "ТрампИрантай шинэ татвар тулгах тухай сүрдүүлэж, Тегерантай харилцаа хурцадсан байна."
CORRECT MONGOLIAN: "Дональд Трамп Ираны газрын тосны импортод 25%-ийн шинэ татвар тогтоохоор сүрдүүллээ. Энэ нь Тегерантай үл ойлголцлыг гүнзгийрүүлж, эрчим хүчний зах зээлд бухимдал үүсгэв."
WHY: SPACE between "Трамп" and "Ираны" (never concatenate proper nouns), full first name (Дональд Трамп), active voice, past tense, no literal "rattle" calque.

EXAMPLE 6 (Mining / Mongolia-relevant):
ENGLISH INPUT: "Rio Tinto raised Oyu Tolgoi's 2026 copper production guidance to 580,000 tonnes, citing faster underground ramp-up."
WRONG MONGOLIAN: "Рио Тинто компани нь Оюу Толгойн 2026 оны зэсний үйлдвэрлэлийн удирдамжийг 580,000 тонн хүртэл нэмэгдүүлсэн байна."
CORRECT MONGOLIAN: "Rio Tinto компани Оюу Толгойн 2026 оны зэсний үйлдвэрлэлийн төлөвийг 580,000 тонн болгож нэмэгдүүллээ. Газар доорх уурхайн хүчин чадал төлөвлөснөөс хурдан өсөж буйг шалтгаан болгов."
WHY: Rio Tinto kept in Latin (corporate name, widely recognised), Оюу Толгой in Cyrillic (domestic asset), active voice, past tense, "төлөв" instead of awkward "удирдамж".

# FINAL QUALITY CHECK (do this before returning JSON)
1. Read your own output aloud mentally. Does any sentence sound translated/awkward? Rewrite it.
2. Are brand names (Google, AWS, Microsoft, Nvidia, Apple, Tesla, OpenAI, Anthropic) in Latin? If you transliterated any (Гүүгл, Майкрософт, Нвидиа, Амазон, Эпл), fix them.
3. Does the body end with a blank line followed by "Эх сурвалж: <source>"? The blank line is mandatory.
4. Does the headline use an action verb in past tense and stay within 60-80 characters?
5. Is image_caption 3-5 words MAX and punchy enough for a magazine cover?

# OUTPUT FORMAT

Return JSON ONLY. No markdown, no code fences, no commentary.

Required keys:
{
  "headline":        "<60-80 char Mongolian headline following Rule 3>",
  "image_caption":   "<3-5 word punchy phrase for image overlay — think magazine cover>",
  "body":            "<150-250 word Mongolian body in natural journalism tone, ending with blank line then 'Эх сурвалж: <source>'>",
  "category":        "<one of: finance, tech, crypto, ai, business, economy, mongolia>",
  "key_numbers":     ["<extracted numbers, percentages, or tickers>"],
  "dynamic_hashtag": "<single hashtag like #Apple or #Bitcoin>"
}

Examples of good image_caption:
  Full headline: "Microsoft Q1 хүчирхэг үр дүнг зарлаж, AI салбарын өсөлтийг тодотгов"
    → image_caption: "Microsoft AI-аар тэргүүлж байна"
  Full headline: "Bitcoin $100,000-ын босгыг давж, институциональ эрэлт өсөв"
    → image_caption: "Биткойн $100K давав"
  Full headline: "Fed хүүгээ 25 bps бууруулж, инфляцийг зөөллөв"
    → image_caption: "Fed хүүгээ бууруулав"

## Rule 8 — IDIOM BLACKLIST (literal translation хориг)

Англи idiom-уудыг ҮГЧЛЭН орчуулахаас зайлсхий. Доорх mapping-уудыг ашигла:

### Эдийн засаг / шүүмж
❌ "hang out to dry"            → ✅ "хатуу шүүмжлэх"
❌ "kicked the can down the road" → ✅ "шийдвэрийг хойшлуулах"
❌ "moved the goalposts"        → ✅ "шаардлагыг өөрчлөх"
❌ "throw in the towel"         → ✅ "бууж өгөх"
❌ "ahead of the curve"         → ✅ "хүлээлтээс түрүүлэх"
❌ "behind the curve"           → ✅ "хүлээлтээс хоцрох"

### Зах зээл / арилжаа
❌ "bull market"                → ✅ "өсөлтийн зах зээл"
❌ "bear market"                → ✅ "уналтын зах зээл"
❌ "rally"                      → ✅ "огцом өсөлт"
❌ "selloff"                    → ✅ "огцом уналт"
❌ "buying the dip"             → ✅ "уналтын үед худалдан авах"

### Бизнес / удирдлага
❌ "low-hanging fruit"          → ✅ "хялбар хүрэх боломж"
❌ "deep dive"                  → ✅ "нарийвчилсан судалгаа"
❌ "game changer"               → ✅ "тоглоомын дүрэм өөрчлөгч"

### Эрсдэл / уналт
❌ "perfect storm"              → ✅ "эрсдэлийн төвлөрөл"
❌ "red flag"                   → ✅ "сэрэмжлүүлэгч шинж"
❌ "tip of the iceberg"         → ✅ "далд асуудлын зөвхөн нэг хэсэг"

ХАТУУ ДҮРЭМ: Idiom-ыг үгчлэн орчуулсан байж болзошгүй гэж сэжиглэвэл
ҮРГЭЛЖ контекстыг ойлгож, утгыг дахин бичигдсэн Монгол хэлээр илэрхийл.

## Rule 9 — FINANCIAL GLOSSARY (мэргэжлийн нэр томьёо)

### Төв банк, мөнгөний бодлого
- Federal Reserve / Fed     → АНУ-ын Холбооны нөөцийн сан (Fed)
- ECB                       → Европын Төв Банк (ECB)
- BOJ                       → Японы Банк (BOJ)
- interest rate             → бодлогын хүү
- rate cut                  → хүү бууруулалт
- rate hike                 → хүү өсгөлт
- basis points (bps)        → суурь оноо (bps)
- hawkish                   → хатуу мөнгөний бодлоготой
- dovish                    → зөөлөн мөнгөний бодлоготой
- inflation                 → инфляц
- deflation                 → дефляц

### Зах зээл, арилжаа
- equity / equities         → хувьцаа
- bond                      → бонд
- yield                     → өгөөж
- yield curve               → өгөөжийн муруй
- 10-year Treasury yield    → 10 жилийн ТС-ийн бондын өгөөж
- volatility                → зах зээлийн савлагаа
- futures                   → фьючерс
- options                   → опцион

### Компанийн санхүү
- earnings                  → тайлант хугацааны орлого
- EPS                       → нэгж хувьцааны ноогдол ашиг
- revenue                   → нийт орлого
- guidance                  → компанийн тооцоолсон хүлээлт
- beat (earnings)           → хүлээлтээс давах
- miss (earnings)           → хүлээлтээс хоцрох
- buyback                   → хувьцаа эргүүлэн худалдан авах
- IPO                       → IPO (анхдагч нийтийн санал)
- market cap                → зах зээлийн үнэлгээ

### Эдийн засгийн үзүүлэлт
- GDP                       → ДНБ
- CPI                       → Хэрэглээний үнийн индекс (CPI)
- unemployment rate         → ажилгүйдлийн түвшин
- nonfarm payrolls          → хөдөө аж ахуйн бус ажил эрхлэлт

### Крипто
- stablecoin                → тогтвортой коин
- DeFi                      → DeFi (төвлөрөлгүй санхүү)
- ETF                       → ETF (биржийн арилжаатай сан)
- halving                   → халвинг

ХАТУУ ДҮРЭМ: Glossary-д байхгүй нэр томьёог АНГЛИАР Latin-аар үлдээ.
Шинэ Монгол үг ЗОХИОХ ХОРИГ.

## Rule 10 — ANTI-FABRICATION (хиймэл үг бий болгох хориг)

Орчуулга нь Монгол хэлний бодит, өргөн хэрэглэгддэг үг дээр л суурилна.

❌ ХОРИГ:
- Шинэ Монгол үг ЗОХИОХГҮЙ
- Англи verb-ыг "-лах/-лэх" суффикс залгахгүй
- Анхдагч мэддэггүй нэр томьёог "санасан Монгол үг" гэж бичихгүй

❌ Production-ийн жишээ алдаа:
- "сүүлчүүлэх"   → ✅ "сүүлд хоцроох"
- "Огнозгүй"     → ✅ "огнолгүй", "тогтворгүй"
- "брэйкаут"     → ✅ "breakout" (Latin үлдээ)
- "найм дугаар удаагаа" → ✅ "найм дахь удаагаа"

ХАРАМЖ: Эргэлзэх нэр томьёотой танилцвал АНГЛИАР Latin-аар үлдээ —
энэ бол ОРЧУУЛАГЧИЙН АЛДАА БИШ, ХАРИН МЭРГЭЖЛИЙН ТЭМДЭГ.
"""

# =============================================================================
# ORANGE MARKET WATCH (GENERATED) — unchanged
# =============================================================================

def generate_market_watch_post():
    """
    Orange Market Watch пост-г үүсгэнэ (санхүүгийн товч зурвас).
    Өдөр бүр 9:00-д эхний постоор гарна.
    """
    mnt_now = datetime.now(MNT_TZ)
    today = mnt_now.strftime("%Y.%m.%d")
    headline = ""  # Body header already carries the date — no duplicate headline.

    try:
        from market_data_fetcher import build_market_watch_body
        body = build_market_watch_body()
    except Exception as e:
        print(f"⚠️ Market data татаж чадсангүй: {e}")
        body = f"""📊 Дэлхийн хөрөнгийн зах зээл — {today}

Өнөөдрийн Orange Market Watch- Та манай энэ өдрийн санхүүгийн зурваст тавтай морилно уу. Дэлхийн томоохон биржүүд, валют, түүхий эдийн зах зээлийн гол үзүүлэлтүүдийг өдөр бүр танилцуулна.

💵 Валют ба хүүгийн ханш
Америк доллар, Евро, Япон иен, Хятадын юань зэрэг гол валютын ханш болон АНУ-ын Холбооны нөөцийн банкны бодлогын хүүгийн мэдээллийг хүргэнэ.

📈 Хөрөнгийн зах зээл
S&P 500, Nasdaq, Nikkei, Shanghai Composite зэрэг индексүүд нь дэлхийн зах зээлийн эрч хүчийг харуулдаг гол үзүүлэлтүүд юм.

💎 Крипто ба түүхий эд
Bitcoin, Ethereum-ийн үнэ, мөн алт, нефть, зэсийн дэлхийн зах зээлийн ханш нь хөрөнгө оруулагчдын анхаарлын төвд байна.

Дэлгэрэнгүй мэдээллийг www.orangenews.mn сайтаас уншина уу."""

    return {
        "category": "market_watch",
        "badge": "📊 ORANGE MARKET WATCH",
        "headline": headline,
        "image_caption": f"Orange Market Watch {today}",
        "post_text": body,
        "full_post": build_full_post("market_watch", headline, body, "#OrangeMarket"),
        "dynamic_hashtag": "#OrangeMarket",
        "key_numbers": [],
        "hashtags": ["#OrangeNews", "#Finance", "#MarketWatch", "#DailyMarket"],
        "original_url": "https://www.orangenews.mn",
        "original_title": f"Orange Market Watch {today}",
        "source": "Orange News",
        "score": 10.0,
        "is_market_watch": True,
        "use_market_watch_image": True,
        "type": "market_watch"
    }


# =============================================================================
# ТУСЛАХ ФУНКЦ — unchanged
# =============================================================================

def build_hashtags(category_key, dynamic_hashtag):
    """#OrangeNews + категорийн 2 + динамик 1"""
    cat = CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])
    tags = ["#OrangeNews"] + cat["hashtags"]

    if dynamic_hashtag and dynamic_hashtag.strip():
        dh = dynamic_hashtag.strip()
        if not dh.startswith("#"):
            dh = "#" + dh
        if dh not in tags:
            tags.append(dh)

    return " ".join(tags)


def build_full_post(category_key, headline, body, dynamic_hashtag):
    """
    Facebook-д шууд тавих ЭЦСИЙН бүрэн текст.
    Гарчиг + badge + body + footer нэгтгэсэн.
    """
    cat = CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])
    badge = cat["badge"]
    hashtags_line = build_hashtags(category_key, dynamic_hashtag)

    # Body-д "Эх сурвалж:" 2 удаа давхардвал засах
    body = body.replace("Эх сурвалж: Эх сурвалж:", "Эх сурвалж:")

    # Empty headline (e.g. Market Watch — body header carries the date) → skip headline block.
    if headline and headline.strip():
        full_post = f"""{badge}

{headline}

{body}
{FOOTER_LINKS}

{hashtags_line}"""
    else:
        full_post = f"""{badge}

{body}
{FOOTER_LINKS}

{hashtags_line}"""

    return full_post


def clean_post_text(text):
    """Хуучин артефактуудыг цэвэрлэх"""
    if not text:
        return ""
    # Markdown heading устгах
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Хиймэл төгсгөл устгах
    patterns = [
        r"Та үүнийг юу гэж бодож байна\?.*$",
        r"Сэтгэгдэлээ хуваалцаарай.*$",
        r"Монголын хөрөнгө оруулагчдад.*$",
        r"Монголд хамааралтай нь:.*$",
        r"👇.*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE | re.DOTALL)
    return text.strip()


def ensure_source_spacing(body: str, source: str) -> str:
    """
    Guarantee body ends with:
        <body>\n\nЭх сурвалж: <source>
    Strips any existing 'Эх сурвалж: ...' suffix and re-appends with a mandatory blank line.
    """
    if not body:
        return f"\nЭх сурвалж: {source}"
    # Strip any trailing 'Эх сурвалж: X' (with optional preceding whitespace/newlines)
    cleaned = re.sub(
        r"\s*Эх\s*сурвалж\s*[:：]\s*.+\Z",
        "",
        body.strip(),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return f"{cleaned.strip()}\n\nЭх сурвалж: {source}"


# =============================================================================
# GEMINI STARTUP PROBE
# =============================================================================

def get_working_gemini_model():
    """
    Probe candidate Gemini models in priority order. Cache the first working one.
    v8.1: google-genai SDK client pattern (old google-generativeai deprecated).

    Priority:
      1. gemini-2.0-flash (primary, stable)
      2. gemini-2.5-flash
      3. gemini-1.5-flash

    Returns the model name (str) or None if all fail / key missing.
    """
    global ACTIVE_GEMINI_MODEL, _GEMINI_CLIENT

    if not _GENAI_AVAILABLE:
        print("⚠️ google-genai SDK not installed — Claude-only mode.")
        ACTIVE_GEMINI_MODEL = None
        return None

    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ GEMINI_API_KEY not set — skipping Gemini probe, Claude-only mode.")
        ACTIVE_GEMINI_MODEL = None
        return None

    try:
        _GEMINI_CLIENT = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    except Exception as e:
        print(f"⚠️ Gemini Client init failed: {e}")
        ACTIVE_GEMINI_MODEL = None
        return None

    candidates = [GEMINI_MODEL_PRIMARY] + GEMINI_MODEL_FALLBACKS

    for model_name in candidates:
        try:
            t0 = time.time()
            response = _GEMINI_CLIENT.models.generate_content(
                model=model_name,
                contents="Return {\"status\": \"ok\"} as JSON only.",
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    max_output_tokens=20,
                ),
            )
            elapsed = time.time() - t0
            # Touch response to confirm parse
            _ = response.text
            print(f"Gemini model probe: {model_name} → OK (response time {elapsed:.1f}s)")
            ACTIVE_GEMINI_MODEL = model_name
            print(f"ACTIVE_GEMINI_MODEL = {model_name}")
            return model_name
        except Exception as e:
            short_err = f"{type(e).__name__}: {str(e)[:100]}"
            print(f"Gemini model probe: {model_name} → FAIL ({short_err})")

    print("⚠️ All Gemini probes failed. Claude fallback will handle every article.")
    ACTIVE_GEMINI_MODEL = None
    return None


# =============================================================================
# USER PROMPT BUILDER
# =============================================================================

def build_user_prompt(article):
    source  = article.get("source", "Unknown")
    title   = article.get("title", "")
    summary = article.get("summary", "")
    rss_cat = article.get("category", "")

    return f"""Rewrite this English financial news article in professional Mongolian business journalism style, matching the editorial voice of Bloomberg Mongolia, Reuters, and Financial Times. Do not translate word-by-word — reconstruct the meaning in natural Mongolian sentence flow. The output must read as if a senior Mongolian financial editor wrote it from scratch after reading the source.

Follow all 7 critical rules and the 6 few-shot examples from your system prompt. Apply the FINAL QUALITY CHECK before returning.

ENGLISH TITLE: {title}

ENGLISH SUMMARY: {summary}

SOURCE: {source}
RSS CATEGORY HINT: {rss_cat}

Return JSON with these exact keys:
- headline         (string, 60-80 chars, full news headline)
- image_caption    (string, 3-5 words MAX, punchy phrase for image overlay — magazine-cover style)
- body             (string, 150-250 words Mongolian, ends with a blank line then "Эх сурвалж: {source}")
- category         (string, one of: finance, tech, crypto, ai, business, economy, mongolia)
- key_numbers      (array of strings extracted from article)
- dynamic_hashtag  (single hashtag like #Apple or #Bitcoin)

No markdown, no code fences, no explanation. Pure JSON only."""


# =============================================================================
# GEMINI TRANSLATOR
# =============================================================================

def translate_with_gemini(article):
    """
    Call Gemini with ACTIVE_GEMINI_MODEL and MONGOLIAN_EDITOR_SYSTEM_PROMPT.
    v8.1: google-genai client pattern (system_instruction now lives in config).

    Returns: (parsed_dict, latency_ms, prompt_text, response_text)
    Raises: RuntimeError if no active model; JSON/API errors propagate.
    """
    if not ACTIVE_GEMINI_MODEL or _GEMINI_CLIENT is None:
        raise RuntimeError("No active Gemini client — probe failed at startup")

    user_prompt = build_user_prompt(article)

    t0 = time.time()
    response = _GEMINI_CLIENT.models.generate_content(
        model=ACTIVE_GEMINI_MODEL,
        contents=user_prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=MONGOLIAN_EDITOR_SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    latency_ms = int((time.time() - t0) * 1000)

    raw = response.text
    parsed = json.loads(raw)
    return parsed, latency_ms, user_prompt, raw


# =============================================================================
# CLAUDE TRANSLATOR (FALLBACK)
# =============================================================================

def translate_with_claude(article):
    """
    Fallback: call Claude Haiku 4.5 with MONGOLIAN_EDITOR_SYSTEM_PROMPT.

    Returns: (parsed_dict, latency_ms, prompt_text, response_text)
    Raises: JSON/API errors propagate.
    """
    user_prompt = build_user_prompt(article)

    t0 = time.time()
    response = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        system=MONGOLIAN_EDITOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )
    latency_ms = int((time.time() - t0) * 1000)

    raw = response.content[0].text.strip()
    # Strip ```json ... ``` fences if the model adds them
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

    parsed = json.loads(raw)
    return parsed, latency_ms, user_prompt, raw


# =============================================================================
# VALIDATION
# =============================================================================

def validate_translation(headline, body):
    """
    Return a list of validation-warning strings. Non-fatal; never raises.
    Spec 3.6 rules:
      - Headline 60-80 chars (warn only)
      - No CamelCase Cyrillic concatenation errors
      - Body ends with "Эх сурвалж:"
      - No banned phrase "аж ахуйн нэгж"
    """
    warnings = []

    # Headline length
    h_len = len(headline or "")
    if h_len < 60 or h_len > 80:
        warnings.append(f"Headline {h_len} chars (target 60-80)")

    # CamelCase Cyrillic (e.g. "ТрампИран")
    combined = f"{headline or ''} {body or ''}"
    match = CAMELCASE_CYRILLIC_RE.search(combined)
    if match:
        warnings.append(f"Possible concatenation error: '{match.group(0)}'")

    # Source tag
    if body and not SOURCE_TAG_RE.search(body):
        warnings.append("Body does not end with Эх сурвалж")

    # Banned phrases
    haystack = f"{headline or ''}\n{body or ''}"
    for phrase in BANNED_PHRASES:
        if phrase in haystack:
            warnings.append(f"Contains banned phrase {phrase}")

    return warnings


# =============================================================================
# CATEGORY NORMALIZATION
# =============================================================================

def normalize_category(cat_raw):
    """
    Gemini spec returns lowercase: finance|tech|crypto|ai|business|economy.
    Our CATEGORIES dict has "AI" uppercase (downstream compat).
    Map "ai" -> "AI". Unknown -> DEFAULT_CATEGORY ("business").
    """
    if not cat_raw:
        return DEFAULT_CATEGORY, True  # unknown flag
    c = str(cat_raw).strip().lower()
    alias = {"ai": "AI"}
    normalized = alias.get(c, c)
    if normalized in CATEGORIES and normalized != "market_watch":
        return normalized, False
    return DEFAULT_CATEGORY, True


# =============================================================================
# LOG ENTRY BUILDER
# =============================================================================

def build_article_log_entry(
    idx, title_en, api_used,
    gemini_attempted, gemini_success, gemini_error, gemini_latency_ms,
    claude_fallback_used, claude_latency_ms,
    prompt_text, response_text,
    validation_warnings
):
    total = (gemini_latency_ms or 0) + (claude_latency_ms or 0)
    return {
        "article_index": idx,
        "article_title_en": (title_en or "")[:80],
        "api_used": api_used,
        "gemini_attempted": gemini_attempted,
        "gemini_success": gemini_success,
        "gemini_error": gemini_error,
        "gemini_latency_ms": gemini_latency_ms,
        "claude_fallback_used": claude_fallback_used,
        "claude_latency_ms": claude_latency_ms,
        "total_latency_ms": total,
        "input_tokens_est": len(prompt_text or "") // 4,
        "output_tokens_est": len(response_text or "") // 4,
        "cost_estimate_usd": COST_PER_CLAUDE_USD if claude_fallback_used else 0.0,
        "validation_warnings": validation_warnings,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# NATIVE-MONGOLIAN PASSTHROUGH (Phase 6.1)
# =============================================================================
# Articles from native-Mongolian RSS feeds (feed-level category == "mongolia")
# bypass Gemini/Claude entirely. The source byline IS the editorial voice; an
# LLM rewrite would dilute it and burn tokens for zero quality gain.
# =============================================================================

from urllib.parse import urlparse


def _source_domain(article_url: str, fallback: str) -> str:
    try:
        host = urlparse(article_url).netloc.replace("www.", "")
        return host or fallback
    except Exception:
        return fallback


def passthrough_mongolian(article, idx):
    """
    Wrap a native-Mongolian article in the same output schema as a translated
    article — no LLM call. Headline / body come straight from the RSS entry.
    """
    title       = clean_post_text(article.get("title", "") or "")
    summary     = clean_post_text(article.get("summary", "") or "")
    source      = article.get("source", "Unknown")
    article_url = article.get("url") or article.get("link", "")

    domain = _source_domain(article_url, source)
    body   = ensure_source_spacing(summary or title, domain)

    # Source-derived hashtag (e.g. "ikon.mn" → "#ikon")
    brand = domain.split(".")[0] if "." in domain else domain
    dynamic_hashtag = f"#{brand}" if brand else "#Mongolia"

    category      = "mongolia"
    image_caption = (title[:40].strip() if title else "МОНГОЛ")
    full_post     = build_full_post(category, title, body, dynamic_hashtag)

    output = {
        "category":        category,
        "badge":           CATEGORIES[category]["badge"],
        "headline":        title,
        "image_caption":   image_caption,
        "post_text":       full_post,
        "body_only":       body,
        "full_post":       full_post,
        "dynamic_hashtag": dynamic_hashtag,
        "key_numbers":     [],
        "hashtags":        build_hashtags(category, dynamic_hashtag).split(),
        "original_url":    article_url,
        "original_title":  title,
        "url":             article_url,
        "source":          source,
        "score":           article.get("score", 0),
        "is_market_watch": False,
        "type":            "news",
    }

    log_entry = build_article_log_entry(
        idx, title, "passthrough_mn",
        gemini_attempted=False, gemini_success=False, gemini_error=None,
        gemini_latency_ms=None,
        claude_fallback_used=False, claude_latency_ms=None,
        prompt_text="", response_text="",
        validation_warnings=[],
    )
    return output, log_entry


# =============================================================================
# ORCHESTRATOR — Gemini → (fail) → Claude → validate → assemble
# =============================================================================

def translate_article(article, idx):
    """
    Returns: (output_dict_or_None, log_entry)
    """
    # Native-Mongolian sources skip the LLM entirely — feed-level category
    # set by orange_rss_collector marks the source language.
    if article.get("category") == "mongolia":
        return passthrough_mongolian(article, idx)

    article_url = article.get("url") or article.get("link", "")
    title_en    = article.get("title", "")

    gemini_attempted     = bool(ACTIVE_GEMINI_MODEL)
    gemini_success       = False
    gemini_error         = None
    gemini_latency       = None
    claude_fallback_used = False
    claude_latency       = None
    parsed               = None
    prompt_text          = ""
    response_text        = ""
    api_used             = "failed"

    # --- Try Gemini first
    if gemini_attempted:
        try:
            parsed, gemini_latency, prompt_text, response_text = translate_with_gemini(article)
            gemini_success = True
            api_used = "gemini"
        except Exception as e:
            gemini_error = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"  ⚠️ Gemini failed: {gemini_error}")

    # --- Fallback to Claude
    if not gemini_success:
        try:
            parsed, claude_latency, prompt_text, response_text = translate_with_claude(article)
            claude_fallback_used = True
            api_used = "claude"
        except Exception as e:
            print(f"  ❌ Claude fallback also failed: {type(e).__name__}: {str(e)[:200]}")
            api_used = "failed"

    # --- If both failed, emit failure log and return
    if parsed is None:
        log_entry = build_article_log_entry(
            idx, title_en, api_used,
            gemini_attempted, gemini_success, gemini_error, gemini_latency,
            claude_fallback_used, claude_latency,
            prompt_text, response_text,
            ["translation failed: no output from either API"]
        )
        return None, log_entry

    # --- Extract fields
    headline        = clean_post_text(parsed.get("headline", ""))
    body            = clean_post_text(parsed.get("body", ""))
    image_caption   = (parsed.get("image_caption") or "").strip()
    cat_raw         = parsed.get("category", DEFAULT_CATEGORY)
    dynamic_hashtag = parsed.get("dynamic_hashtag", "") or ""
    key_numbers     = parsed.get("key_numbers", []) or []

    category, cat_unknown = normalize_category(cat_raw)

    # --- Defensive post-processing: guarantee blank line before "Эх сурвалж:"
    body = ensure_source_spacing(body, article.get("source", "Unknown"))

    # --- Validate
    validation_warnings = []
    if cat_unknown:
        validation_warnings.append(f"Unknown category '{cat_raw}', defaulted to '{DEFAULT_CATEGORY}'")
    validation_warnings += validate_translation(headline, body)
    if not image_caption:
        validation_warnings.append("Missing image_caption — will fall back to truncated headline")

    # --- Assemble full post
    full_post = build_full_post(category, headline, body, dynamic_hashtag)

    output = {
        "category": category,
        "badge": CATEGORIES[category]["badge"],
        "headline": headline,
        "image_caption": image_caption,
        "post_text": full_post,
        "body_only": body,
        "full_post": full_post,
        "dynamic_hashtag": dynamic_hashtag,
        "key_numbers": key_numbers,
        "hashtags": build_hashtags(category, dynamic_hashtag).split(),
        "original_url": article_url,
        "original_title": title_en,
        "url": article_url,
        "source": article.get("source", "Unknown"),
        "score": article.get("score", 0),
        "is_market_watch": False,
        "type": "news",
    }

    log_entry = build_article_log_entry(
        idx, title_en, api_used,
        gemini_attempted, gemini_success, gemini_error, gemini_latency,
        claude_fallback_used, claude_latency,
        prompt_text, response_text, validation_warnings,
    )

    return output, log_entry


# =============================================================================
# RUN LOG (JSON) + STDOUT SUMMARY
# =============================================================================

def write_run_log(run_data):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"translation_{run_data['run_id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run_data, f, ensure_ascii=False, indent=2)
    return path


def print_run_summary(run_data):
    articles = run_data["articles"]
    totals   = run_data["totals"]
    n        = len(articles)

    gemini_latencies = [a["gemini_latency_ms"] for a in articles
                        if a.get("gemini_success") and a.get("gemini_latency_ms")]
    claude_latencies = [a["claude_latency_ms"] for a in articles
                        if a.get("claude_fallback_used") and a.get("claude_latency_ms")]
    gemini_avg = (sum(gemini_latencies) / len(gemini_latencies) / 1000) if gemini_latencies else 0
    claude_avg = (sum(claude_latencies) / len(claude_latencies) / 1000) if claude_latencies else 0

    def pct(x):
        return f"{(x / n * 100):.0f}%" if n else "0%"

    claude_cost = totals["claude_fallback"] * COST_PER_CLAUDE_USD
    total_cost  = claude_cost  # Gemini free tier

    all_warnings = [(a["article_index"], w) for a in articles for w in a.get("validation_warnings", [])]

    print("\n======================================")
    print("Orange News Translator — Run Summary")
    print("======================================")
    print(f"Run started:  {run_data['started_utc']}")
    print(f"Run finished: {run_data['finished_utc']}")
    print(f"Duration:     {run_data['duration_s']:.1f} seconds\n")

    print(f"Articles processed: {n}")
    print(f"  Gemini success:    {totals['gemini_success']}  ({pct(totals['gemini_success'])})")
    print(f"  Claude fallback:   {totals['claude_fallback']}  ({pct(totals['claude_fallback'])})")
    print(f"  Passthrough (MN):  {totals.get('passthrough_mn', 0)}  ({pct(totals.get('passthrough_mn', 0))})")
    print(f"  Both failed:       {totals['both_failed']}  ({pct(totals['both_failed'])})\n")

    print("Latency:")
    print(f"  Gemini avg: {gemini_avg:.1f}s")
    print(f"  Claude avg: {claude_avg:.1f}s")
    print(f"  Total:      {run_data['duration_s']:.1f}s\n")

    print("Cost estimate:")
    print(f"  Gemini:     $0.000  (free tier)")
    print(f"  Claude:     ${claude_cost:.3f}  ({totals['claude_fallback']} articles x ~${COST_PER_CLAUDE_USD:.3f})")
    print(f"  Total:      ${total_cost:.3f}\n")

    print(f"Validation warnings: {len(all_warnings)}")
    for idx, w in all_warnings:
        print(f"  [{idx}] {w}")

    print(f"\nFull log: logs/translation_{run_data['run_id']}.json")
    print("======================================\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("🟠 Orange News Translator v8 — Gemini primary, Claude fallback\n")

    started_utc = datetime.now(timezone.utc)
    run_id      = started_utc.strftime("%Y%m%d_%H%M")

    # Startup probe
    get_working_gemini_model()

    # Require at least one key
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_gemini and not has_claude:
        print("❌ Neither GEMINI_API_KEY nor ANTHROPIC_API_KEY is set. Aborting.")
        sys.exit(1)

    if not os.path.exists(INPUT_FILE):
        print(f"❌ {INPUT_FILE} not found")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"\n📥 {len(articles)} articles to translate...\n")

    # Market Watch first (generated, not translated)
    print("📊 Generating Orange Market Watch...")
    market_watch = generate_market_watch_post()
    translated   = [market_watch]
    article_logs = []
    print(f"  ✅ {market_watch['badge']} | {market_watch.get('image_caption', '')}\n")

    # Translate each news article
    for i, article in enumerate(articles):
        title_preview = article.get('title', 'Untitled')[:60]
        print(f"[{i+1}/{len(articles)}] {title_preview}...")
        output, log_entry = translate_article(article, i)
        article_logs.append(log_entry)
        if output:
            translated.append(output)
            print(f"  ✅ {log_entry['api_used']:6s} | {output['badge']} | {output['headline'][:60]}")
        else:
            print("  ❌ Skipped (both APIs failed)")
        print()

    # Persist translations
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    # Aggregate run stats
    finished_utc = datetime.now(timezone.utc)
    duration_s   = (finished_utc - started_utc).total_seconds()

    gemini_success  = sum(1 for a in article_logs if a["api_used"] == "gemini")
    claude_fallback = sum(1 for a in article_logs if a["api_used"] == "claude")
    passthrough_mn  = sum(1 for a in article_logs if a["api_used"] == "passthrough_mn")
    both_failed     = sum(1 for a in article_logs if a["api_used"] == "failed")
    cost_usd        = claude_fallback * COST_PER_CLAUDE_USD

    run_data = {
        "run_id":        run_id,
        "started_utc":   started_utc.isoformat(),
        "finished_utc": finished_utc.isoformat(),
        "duration_s":    duration_s,
        "model_primary": ACTIVE_GEMINI_MODEL or "none",
        "model_fallback": CLAUDE_MODEL,
        "totals": {
            "articles":        len(article_logs),
            "gemini_success":  gemini_success,
            "claude_fallback": claude_fallback,
            "passthrough_mn":  passthrough_mn,
            "both_failed":     both_failed,
            "cost_usd":        cost_usd,
        },
        "articles": article_logs,
    }

    log_path = write_run_log(run_data)
    print_run_summary(run_data)

    # Category breakdown (legacy output preserved)
    cat_counts = {}
    for post in translated:
        cat_counts[post["category"]] = cat_counts.get(post["category"], 0) + 1
    print("📊 Категорийн хуваарилалт:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        badge = CATEGORIES.get(cat, {}).get("badge", "❓")
        print(f"  {badge}: {count}")

    print(f"\n📁 Translations: {OUTPUT_FILE}")
    print(f"📁 Log file:     {log_path}\n")


if __name__ == "__main__":
    main()
