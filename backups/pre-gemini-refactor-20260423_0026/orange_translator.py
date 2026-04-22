"""
Orange News — Translator v7 FINAL
==================================
Бүх засварыг нэгтгэсэн эцсийн хувилбар

Шинэчлэлт v5 → v7:
1. ✅ full_post талбар заавал үүсгэсэн (fb_poster-т зориулсан)
2. ✅ RSS collector-н "url" талбарыг зөв уншина (link биш)
3. ✅ Orange Market Watch пост автоматаар үүсгэнэ (GENERATED, RSS-ээс биш)
4. ✅ AI smell 50+ хориг (v6.1)
5. ✅ Passive construction бүрэн хориглов
6. ✅ Үгчилсэн орчуулга хориг
7. ✅ 4-үе шаттай Chain of Thought
8. ✅ Instagram footer footer-т орсон
9. ✅ "Та үүнийг яах бодож байна?" гэх мэт хуучин артефакт устгасан

Author: Azurise AI Master Architect
Date: April 18, 2026
"""

import os
import json
import sys
import certifi
from datetime import datetime, timezone

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

import httpx as _httpx
import anthropic

# =============================================================================
# CONFIG
# =============================================================================

INPUT_FILE = "top_news.json"
OUTPUT_FILE = "translated_posts.json"

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2500

client = anthropic.Anthropic(
    http_client=_httpx.Client(verify=certifi.where())
)

# =============================================================================
# КАТЕГОРИ (7 төрөл)
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
    "market_watch": {
        "badge": "📊 ORANGE MARKET WATCH",
        "hashtags": ["#Finance", "#MarketWatch", "#DailyMarket"],
    }
}

DEFAULT_CATEGORY = "business"

# =============================================================================
# FOOTER (full_post-д оруулна)
# =============================================================================

FOOTER_LINKS = """🌐 Вэбсайт: https://www.orangenews.mn
📘 Facebook: https://www.facebook.com/orangenews.mn
📸 Instagram: https://www.instagram.com/orangenews.official
🧵 Threads: https://www.threads.net/@orangenews.official"""


# =============================================================================
# BLOOMBERG SYSTEM PROMPT v7 (50+ хориг, 4 алхам)
# =============================================================================

BLOOMBERG_SYSTEM = """Чи бол Монголын тэргүүлэх санхүү-бизнесийн мэдээллийн сайт Orange News-ийн
ахлах орчуулагч редактор. Bloomberg, Financial Times, Reuters-ийн хэв маягаар
ажилладаг, мөн Монголд Lemon Press шиг мэргэжлийн сэтгүүлзүйн хэл найруулгыг
баримталдаг.

# НЭН ТЭРГҮҮНИЙ ЗАРЧИМ

⚠️ ЧИ ЯГ "МОНГОЛ ХҮНИЙ БИЧСЭН" ШИГ БИЧНЭ. ХЭРВЭЭ УНШИГЧ "ЭНЭ AI-ААР
ОРЧУУЛСАН БАЙНА" ГЭЖ БОДВОЛ ЧИ БҮРЭН АЛДСАН ГЭСЭН ҮГ.

# 4 ҮНДСЭН ЗАРЧИМ

1. **УТГА ХАДГАЛЖ, ХЭЛБЭРИЙГ ЗАСАХ**
   Англи мэдээний ҮГИЙГ орчуулахгүй, САНААГ нь Монгол хэлний ердийн
   бүтцээр шинээр бич.

   ❌ "Tesla's Q3 earnings beat Wall Street expectations with revenue
       of $25.18 billion, up 8% year-over-year"
   ❌ "Тесла Q3 орлого нь Уолл Стриттийн төлөвлөгөөнөөс давж, 25.18
       тэрбум долларт хүрсэн нь жилийн өмнөхөөс 8 хувийн өсөлттэй гарлаа"
       (❌ үгчилсэн)
   ✅ "Тэсла гуравдугаар улирлын орлогоо 25.18 тэрбум долларт хүргэж,
       өнгөрсөн оны мөн үеэс 8 хувиар нэмэгдүүлэв. Энэ нь шинжээчдийн
       хүлээлтээс давсан үзүүлэлт юм."

2. **МОНГОЛ СЭТГҮҮЛЧИЙН ХЭЛНИЙ ТЕМБР**
   Лемон Пресс, ikon.mn-ийн сайн сэтгүүлч яаж бичдэг вэ?

   ✅ "Банк бүх салбараараа шинэ үйлчилгээг нэвтрүүллээ."
   ✅ "Компани гуравдугаар улирлын тайлангаа танилцуулж, 2.5 тэрбум
       төгрөгийн цэвэр ашигтай ажилласнаа мэдэгдэв."
   ✅ "Инфляцын түвшин 7.4 хувьд хүрснийг ҮСХ-ноос мэдээллээ."

3. **PASSIVE-ЭЭС ЗАЙЛСХИЙ**
   ❌ "Байгаа нь тогтоогджээ" → ✅ "... болохыг илрүүллээ"
   ❌ "Шаардлагатай байгаа нь мэдэгдэв" → ✅ "... хэрэгтэй гэв"
   ❌ "Хаагдсан байна" → ✅ "хаагдлаа"
   ❌ "Төлөвлөгөөнөөсөө давсан үнээр хаагдлаа" → ✅ "төлөвлөгөөнөөсөө
       илүү үнээр дуусгав"

4. **БОГИНО, ТОДОРХОЙ ӨГҮҮЛБЭР**
   Нэг өгүүлбэрт 3-аас дээш "ба/бөгөөд/болон" байвал ЗААВАЛ хэсэглэ.

# 4 АЛХАМТАЙ CHAIN OF THOUGHT

АЛХАМ 1 — ОЙЛГОХ: ХЭН + ЮУ + ЯАГААД + ТОО/НЭР/ОГНОО
АЛХАМ 2 — ДАХИН БИЧИХ: Монгол бүтцээр, active-аар
АЛХАМ 3 — AI SMELL ШАЛГАХ: Доорх жагсаалтыг устгах
АЛХАМ 4 — МОНГОЛ УНШИГЧИЙН НҮДЭЭР: 30 настай Монгол залуу уншаад
   "энэ Монгол хэлний жам ёсоор бичигдсэн үү?" гэж өөрөөс асуу.
   Хэрэв эвгүй сонсогдож байвал ДАХИН бич.

# ХАТУУ ХОРИГ (AI smell)

## A. PASSIVE CONSTRUCTION
❌ "Байгаа нь тогтоогджээ" → ✅ "илрүүллээ"
❌ "Хаагдсан байна" → ✅ "хаагдлаа"
❌ "Шаардлагатай байгаа нь мэдэгдэв" → ✅ "хэрэгтэй гэв"
❌ "Зогсоож чадахгүй байгаа нь тогтоогджээ" → ✅ "зогсоож чаддаггүй"

## B. ҮГЧИЛСЭН ОРЧУУЛГА
❌ "Төлөвлөгөөнөөсөө давсан үнээр хаагдлаа" → ✅ "илүү үнээр дуусгав"
❌ "Жилийн өмнөхөөс 8 хувийн өсөлттэй гарлаа" → ✅ "өнгөрсөн оны мөн
   үеэс 8 хувиар нэмэгдэв"
❌ "Маркетын хүлээлтээс давсан" → ✅ "зах зээлийн хүлээлтээс илүү"
❌ "Хөрөнгө оруулалт хийхэд зориулагдсан" → ✅ "хөрөнгө оруулалтад
   зориулсан"

## C. АЛБАН ЁСНЫ ОLONRMAL
❌ "Тэмдэглэлээ" → ✅ "тэмдэглэв"
❌ "...хэмээн мэдэгдэж байна" → ✅ "...гэв"
❌ "Хүрээнд", "холбогдуулан" → шууд үг
❌ "Энэхүү" → ✅ "Энэ"
❌ "Тус" (хэт формал) → ✅ "Энэ"

## D. AI-ИЙН ДУРТАЙ ҮГС
❌ "Даван туулсан" → ✅ "давж гарсан"
❌ "Анхаарал татаж байна" → БҮРЭН УСТГА
❌ "Томоохон боломжтой гэж дүгнэж байна" → ✅ "боломжтой"
❌ "Шилдэг үр дүнтэй" → ✅ "гүйцэтгэлээрээ тэргүүлж буй"
❌ "Туйлын чухал" → баталгаатай тоо бичих

## E. МОНГОЛТОЙ ХОЛБОГДОЛГҮЙ ХИЙМЭЛ ҮГ
❌ "Монголын хөрөнгө оруулагчдад..." → БҮГДИЙГ УСТГА
❌ "Монголд хамааралтай нь..." → БҮГДИЙГ УСТГА
❌ "Та үүнийг юу гэж бодож байна?" → БҮРЭН ХОРИГ
❌ "Сэтгэгдэлээ хуваалцаарай" → БҮРЭН ХОРИГ
❌ "👇" → БҮРЭН ХОРИГ

## F. ДАВТАГДСАН CONNECTOR
❌ "Үүнд" / "Ингэснээр" 2 удаа → Нэг л удаа
❌ "Мөн" өгүүлбэр бүрийн эхэнд → өөрчил
❌ "Харин" хэт олон → багасга

## G. FORM ШААРДЛАГА
❌ Эхний өгүүлбэрт асуулт → ХОРИГ
❌ Emoji бичвэрийн дотор → ХОРИГ
❌ Эхний өгүүлбэрт эх сурвалжийн нэр → ХОРИГ
❌ Markdown: # ## ** __ ` → БҮРЭН ХОРИГ (зөвхөн энгийн текст)

# ГАРЧГИЙН ДҮРЭМ (8-14 үг)

Бүтэц: [СУБЪЕКТ] + [VERB] + [ЯАГААД/ОРЧИН]

✅ "NVIDIA Хятад руу H20 чипээ эргүүлэн экспортлох зөвшөөрөл авлаа"
✅ "Bitcoin $90,000 давж, ETF-д 420 сая долларын орлого бүртгэгдэв"

❌ "Аж ахуйн нэгжүүдийн 90 хувь нь AI агентын гуравдагч шатны
    халдлагаас хамгаалж чадахгүй" (passive, хэт урт)

# ЭХНИЙ ӨГҮҮЛБЭРИЙН ДҮРЭМ (25-35 үг)

- ХЭН + ЮУ + ХЭЗЭЭ/ХААНА шууд
- Нэр, тоо, огноо орсон
- Active, passive биш
- Англи бүтэц хуулахгүй
- Эх сурвалжийн нэрийг эхэнд БИЧИХГҮЙ (доор бичнэ)

✅ "Apple өнөөдөр iPhone 17 загвараа танилцуулж, шинэ M5 чиптэй
    загваруудаа 9-р сарын 19-нд зах зээлд гаргахаа зарлав."

# КАТЕГОРИ СОНГОХ

- finance: банк, хадгаламж, зээл, сан, ETF
- tech: Apple, Google, Microsoft, Nvidia зэрэг компани
- crypto: Bitcoin, Ethereum, blockchain
- AI: ChatGPT, LLM, AI agent, роботехник
- business: M&A, IPO, startup, Fortune 500
- economy: инфляци, GDP, төв банкны хүү, улс орон хоорондын худалдаа

# ДИНАМИК HASHTAG (1 нэмэлт)

- Компани: #NVIDIA, #Apple, #Tesla, #Microsoft
- Крипто: #Bitcoin, #Ethereum
- Улс: #China, #USA, #Japan
- Сэдэв: #ETF, #Semiconductors, #EV

# ГАРГАХ ФОРМАТ (ЗӨВХӨН JSON)

{
  "category": "finance|tech|crypto|AI|business|economy",
  "headline": "Гарчиг (8-14 үг, active verb)",
  "post_text": "Эхний өгүүлбэр (25-35 үг).\\n\\n2-р параграф (тоо, иш, контекст).\\n\\n3-р параграф.\\n\\nЭх сурвалж: [нэр]",
  "dynamic_hashtag": "#CompanyOrTopic",
  "key_numbers": ["$87,000", "+2.5%"]
}
"""

# =============================================================================
# ORANGE MARKET WATCH (GENERATED)
# =============================================================================

def generate_market_watch_post():
    """
    Orange Market Watch пост-г үүсгэнэ (санхүүгийн товч зурвас).
    Өдөр бүр 9:00-д эхний постоор гарна.

    V7.1 шинэчлэлт:
    - Монголбанк API-аас валютын бодит ханш
    - Yahoo Finance API-аас индекс, крипто, түүхий эдийн үнэ
    - Хэрвээ API татагдахгүй бол fallback текст
    """
    today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    headline = f"ORANGE MARKET WATCH: {today}"

    # Бодит market data татах оролдлого
    try:
        from market_data_fetcher import build_market_watch_body
        body = build_market_watch_body()
    except Exception as e:
        print(f"⚠️ Market data татаж чадсангүй: {e}")
        # Fallback: ерөнхий текст (Mongol-related хэсгийг устгасан)
        body = """📊 Дэлхийн хөрөнгийн зах зээл

Өнөөдрийн Orange Market Watch таны өдрийн эхний санхүүгийн зурваст тавтай морилно уу. Дэлхийн томоохон биржүүд, валют, түүхий эдийн зах зээлийн гол үзүүлэлтүүдийг өдөр бүр танилцуулна.

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
        "use_market_watch_image": True,  # image_generator-т зориулсан туг
        "type": "market_watch"
    }


# =============================================================================
# ТУСЛАХ ФУНКЦ
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

    full_post = f"""{badge}

{headline}

{body}

---

{FOOTER_LINKS}

{hashtags_line}"""

    return full_post


def clean_post_text(text):
    """Хуучин артефактуудыг цэвэрлэх"""
    import re

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


def translate_article(article):
    """Нэг мэдээг Claude API-р орчуулах"""

    # RSS collector-д url, translator-т link гэсэн ялгаа засах
    article_url = article.get("url") or article.get("link", "")

    user_prompt = f"""Дараах англи мэдээг Orange News-ийн Bloomberg/Lemon Press хэв маягаар
Монгол хэлэнд дахин бич.

=== ЭХ МЭДЭЭ ===

Гарчиг: {article.get('title', '')}

Агуулга:
{article.get('summary', '')}

Эх сурвалж: {article.get('source', 'Unknown')}
URL: {article_url}

=== ДААЛГАВАР ===

1. 4-алхмын логикийг дагаж ажилла
2. Категорийг зөв сонго
3. Динамик hashtag гарга
4. AI smell, passive, үгчилсэн орчуулга УСТГАСАН байх
5. Markdown (# ## **) БҮРЭН ХОРИГ
6. Эхний өгүүлбэрт эх сурвалжийн нэр БИЧИХГҮЙ
7. Зөвхөн JSON буцаа (код блок, тайлбар хэрэггүй)
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=BLOOMBERG_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_text = response.content[0].text.strip()

    # ```json блокыг цэвэрлэх
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse алдаа: {e}")
        print(f"  Raw text:\n{raw_text[:500]}")
        return None

    category = result.get("category", DEFAULT_CATEGORY).lower()
    if category not in CATEGORIES or category == "market_watch":
        category = DEFAULT_CATEGORY

    headline = clean_post_text(result.get("headline", ""))
    body = clean_post_text(result.get("post_text", ""))
    dynamic_hashtag = result.get("dynamic_hashtag", "")

    # ЭЦСИЙН full_post үүсгэх
    full_post = build_full_post(category, headline, body, dynamic_hashtag)

    return {
        "category": category,
        "badge": CATEGORIES[category]["badge"],
        "headline": headline,
        "post_text": full_post,    # fb_poster.py format_post() энийг авна
        "body_only": body,          # зөвхөн body (backup)
        "full_post": full_post,     # шинэ poster-т зориулсан
        "dynamic_hashtag": dynamic_hashtag,
        "key_numbers": result.get("key_numbers", []),
        "hashtags": build_hashtags(category, dynamic_hashtag).split(),
        "original_url": article_url,
        "original_title": article.get("title", ""),
        "url": article_url,          # image_generator compatibility
        "source": article.get("source", "Unknown"),
        "score": article.get("score", 0),
        "is_market_watch": False,
        "type": "news"
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("🟠 Orange News Translator v7 FINAL эхэлж байна...\n")
    print("📌 V7: Market Watch + full_post + 50+ AI smell хориг\n")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY олдсонгүй!")
        sys.exit(1)

    if not os.path.exists(INPUT_FILE):
        print(f"❌ {INPUT_FILE} олдсонгүй!")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"📥 {len(articles)} мэдээ орчуулна...\n")

    # 1. Market Watch эхлээд үүсгэнэ (хамгийн эхний пост)
    print("📊 Orange Market Watch үүсгэх...")
    market_watch = generate_market_watch_post()
    translated = [market_watch]
    print(f"  ✅ {market_watch['headline']}\n")

    # 2. Бусад мэдээг орчуулах
    for i, article in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] {article.get('title', 'Untitled')[:60]}...")

        try:
            result = translate_article(article)
            if result:
                translated.append(result)
                print(f"  ✅ {result['badge']} | {result['headline'][:60]}")
            else:
                print(f"  ⚠️ Алгассан")
        except Exception as e:
            print(f"  ❌ Алдаа: {e}")
            continue

        print()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    # Категори-оор хуваарилалт
    cat_counts = {}
    for post in translated:
        cat = post["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"\n{'='*60}")
    print(f"✅ Амжилттай! {len(translated)} пост бэлэн ({len(articles)} мэдээ + 1 Market Watch)")
    print(f"📁 Хадгалсан: {OUTPUT_FILE}")
    print(f"\n📊 Категорийн хуваарилалт:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        badge = CATEGORIES.get(cat, {}).get("badge", "❓")
        print(f"  {badge}: {count}")

    print(f"\n⏰ Scheduling план:")
    print(f"  09:00 — Orange Market Watch (эхний пост, шууд)")
    for i in range(1, len(translated)):
        print(f"  {10+i-1:02d}:00 — {translated[i]['headline'][:50]}...")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
