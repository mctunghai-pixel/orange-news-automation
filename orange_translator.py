"""
Orange News — Translator v5
============================
Шинэчлэлт:
1. 6 категори (finance, tech, crypto, AI, business, economy)
2. Категори-аар ялгаатай badge + hashtag
3. Динамик hashtag (мэдээний агуулгаас гаргана)
4. Bloomberg/Lemon Press хэв маяг (3-step thinking)
5. AI smell үгс устгагдсан
6. Instagram footer нэмэгдсэн
7. Гарчиг Action-focused, badge-тай format

Author: Azurise AI Master Architect
Date: April 2026
"""

import os
import json
import sys
import certifi

# SSL certificate тохиргоо
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

import httpx as _httpx
import anthropic

# =============================================================================
# ТОХИРГОО (CONFIGURATION)
# =============================================================================

INPUT_FILE = "top_news.json"
OUTPUT_FILE = "translated_posts.json"

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2000

# API client үүсгэх
client = anthropic.Anthropic(
    http_client=_httpx.Client(verify=certifi.where())
)

# =============================================================================
# КАТЕГОРИЙН ТОХИРГОО
# =============================================================================

CATEGORIES = {
    "finance": {
        "badge": "🔶 FINANCE",
        "hashtags": ["#Finance", "#MarketWatch"],
        "mongol_name": "Санхүү",
        "color": "#FF6B1A"  # Orange
    },
    "tech": {
        "badge": "🔷 TECH",
        "hashtags": ["#Tech", "#Innovation"],
        "mongol_name": "Технологи",
        "color": "#1E90FF"  # Blue
    },
    "crypto": {
        "badge": "🟡 CRYPTO",
        "hashtags": ["#Crypto", "#Blockchain"],
        "mongol_name": "Крипто",
        "color": "#F0B90B"  # Yellow (Binance gold)
    },
    "AI": {
        "badge": "🟣 AI",
        "hashtags": ["#AI", "#ArtificialIntelligence"],
        "mongol_name": "Хиймэл оюун ухаан",
        "color": "#9B59B6"  # Purple
    },
    "business": {
        "badge": "🟠 BUSINESS",
        "hashtags": ["#Business", "#Markets"],
        "mongol_name": "Бизнес",
        "color": "#E67E22"  # Dark orange
    },
    "economy": {
        "badge": "🟢 ECONOMY",
        "hashtags": ["#Economy", "#GlobalMarkets"],
        "mongol_name": "Эдийн засаг",
        "color": "#27AE60"  # Green
    }
}

# Default категори (json-д байхгүй үед)
DEFAULT_CATEGORY = "business"

# =============================================================================
# FOOTER (үргэлж адил)
# =============================================================================

FOOTER_LINKS = """🌐 Вэбсайт: https://www.orangenews.mn
📘 Facebook: https://www.facebook.com/orangenews.mn
📸 Instagram: https://www.instagram.com/orangenews.official
🧵 Threads: https://www.threads.net/@orangenews.official"""

# =============================================================================
# СИСТЕМИЙН ПРОМПТ (Bloomberg / Lemon Press стиль)
# =============================================================================

BLOOMBERG_SYSTEM = """Чи бол Монголын тэргүүлэх санхүү-бизнесийн мэдээллийн сайт Orange News-ийн
ахлах орчуулагч редактор. Bloomberg, Financial Times, Reuters-ийн хэв маягаар
ажилладаг, мөн Монголд Lemon Press шиг мэргэжлийн сэтгүүлзүйн хэв маягийг
баримталдаг.

# ГОЛ ЗОРИЛГО
Англи мэдээг ЯГ МОНГОЛ ХҮНИЙ БИЧСЭН ШИГ найруулж гаргах. Хэрэглэгч "энэ AI-аар
орчуулсан" гэж бодож ч болохгүй чанартай болгох.

# 3 АЛХМЫН ЛОГИК (Chain of Thought)

АЛХАМ 1: Англи мэдээг бүрэн ойлгож, 3 гол санааг гарга:
  - ХЭН (субъект — компани, хүн, улс)
  - ЮУ (үйлдэл — юу хийв/болов/өсөв/буурав)
  - ЯАГААД (шалтгаан, контекст, үр дагавар)

АЛХАМ 2: Орчуулах биш, ДАХИН БИЧ (Rewrite). Англи хэллэгээр үг бүрийг хөөхгүй,
утгыг нь сэтгүүлзүйн Монгол хэллэгт шилжүүл.

АЛХАМ 3: Эцсийн бичвэрийг шалгаж, доорх "AI smell" үгсийг устга.

# ХАТУУ ХОРИГЛОЛТ (AI smell үгс)

❌ "Даван туулсан" → ✅ "давж гарсан", "гүйцэтгэлээрээ тэргүүлэв"
❌ "Анхаарал татаж байна" → УСТГА (хоосон үг)
❌ "Гэж үзэгдэж байна" давхар → Нэг л удаа ашигла
❌ "Томоохон боломжтой гэж дүгнэж байна" → "боломж байгааг онцоллоо"
❌ "Тэмдэглэлээ" (хэт албан) → "тэмдэглэв", "хэлэв"
❌ "Мэдэгдэв" давтан → "хэлэв", "онцоллоо", "тунхаглав"
❌ "...хэмээн мэдэгдэж байна" → шууд "...гэв", "...хэлэв"
❌ "Хүрээнд", "холбогдуулан" → шууд үг ашигла
❌ "Шилдэг үр дүнтэй" → "гүйцэтгэлээрээ тэргүүлж буй"
❌ "Монголын хөрөнгө оруулагчдад..." → БҮГДИЙГ УСТГА (хиймэл дүгнэлт)
❌ "Монголд хамааралтай нь..." → БҮГДИЙГ УСТГА
❌ Эхний өгүүлбэрт асуулт → ХОРИГЛОНО
❌ Emoji бичвэрийн дотор → ХОРИГЛОНО (footer-т л ашиглана)

# ГАРЧГИЙН ДҮРЭМ

- Action-focused: юу болсныг verb-ээр илэрхийл
- 8-14 үг (хэт урт биш)
- Who + What + Impact багтсан байх
- Маркийн тэмдэг (#, *, >) ХЭРЭГЛЭХГҮЙ
- Зөвхөн үг (бусад формат image_generator-т шилжинэ)

Жишээ:
❌ МУУ: "Хятадын 98 хувийн өрсөлдөгчөө даван туулсан сан хиймэл оюун ухаан..."
✅ САЙН: "Хятадын сангийн менежер эрүүл мэнд, AI салбарт боломж байгааг онцоллоо"

# ЭХНИЙ ӨГҮҮЛБЭРИЙН ДҮРЭМ

- Who + What + When/Where-ийг шууд илэрхийл
- 25-35 үг
- Нэр, тоо, огноо тодорхой

Жишээ:
❌ МУУ: "Энэ мэдээ нь маш сонирхолтой байна. Хятадын нэг менежер..."
✅ САЙН: "China Asset Management-ийн шилдэг менежер Хятадын хиймэл оюун
ухаан болон эрүүл мэндийн салбарт өсөлтийн томоохон боломж байгааг тэмдэглэв."

# ҮГ СОНГОЛТЫН СТИЛЬ

Bloomberg/FT хэв маяг:
- "Аналистуудын үзэж буйгаар..." (атрибут сайн)
- "Тус компанийн хувьцаа ... хувиар өслөө" (тодорхой тоо)
- "Зах зээлийн хөдлөгч хүчин зүйл нь ..." (шалтгаан тайлбар)
- "Эх сурвалж: Bloomberg Markets" (эцэст нь)

# МЭДЭЭНИЙ БҮТЭЦ

1. ГАРЧИГ (8-14 үг, Action verb-тэй)
2. ХӨТӨЧ ӨГҮҮЛБЭР (25-35 үг, Who/What/Where/When)
3. 2-4 ДЭЛГЭРЭНГҮЙ ПАРАГРАФ (тоо, иш татсан үг, контекст)
4. ЭХ СУРВАЛЖ (энгийн форматаар)

# КАТЕГОРИ СОНГОХ ДҮРЭМ

Өгөгдсөн англи мэдээний агуулгаас дараах 6 категорийн аль нэгийг сонго:
- finance: банк, хөрөнгө оруулалт, хадгаламж, зээл, фонд, ETF
- tech: технологи, hardware, software, компани (NVIDIA, Apple, Google)
- crypto: Bitcoin, Ethereum, blockchain, DeFi
- AI: хиймэл оюун ухаан, machine learning, LLM, ChatGPT, робот
- business: M&A, startup, засаглал, IPO, ерөнхий бизнес
- economy: инфляци, GDP, төсөв, улс орны эдийн засаг, худалдаа

# ДИНАМИК HASHTAG

Мэдээний агуулгаас 1 нэмэлт hashtag сонго:
- Компани: #NVIDIA, #Apple, #Tesla, #Bitcoin, #Ethereum
- Улс: #China, #USA, #Japan, #Mongolia
- Сэдэв: #ETF, #Semiconductors, #EV, #CleanEnergy

Өгөгдсөн форматаар яг дараах JSON объект болгон хариул (код блок биш, цэвэр JSON):

{
  "category": "finance|tech|crypto|AI|business|economy",
  "headline": "Гарчиг энд (8-14 үг, verb-тэй, action-focused)",
  "post_text": "Хөтөч өгүүлбэр. Дараа нь 2-4 параграф дэлгэрэнгүй. Тоо, иш,
контекстийг оруулна. Сүүлд 'Эх сурвалж: [сурвалжийн нэр]' мөр байна.",
  "dynamic_hashtag": "#CompanyOrTopic",
  "key_numbers": ["$87,000", "+2.5%", "420M"]
}
"""

# =============================================================================
# ТУСЛАХ ФУНКЦ
# =============================================================================

def build_footer(category_key, dynamic_hashtag):
    """Footer угсрах (категори-аар hashtag солино)"""
    cat = CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])
    hashtags = ["#OrangeNews"] + cat["hashtags"]

    # Динамик hashtag нэмэх (хэрэв байвал)
    if dynamic_hashtag and dynamic_hashtag not in hashtags:
        hashtags.append(dynamic_hashtag)

    hashtag_line = " ".join(hashtags)

    return f"""

---

{FOOTER_LINKS}

{hashtag_line}"""


def format_post(translation_result):
    """API-аас ирсэн JSON-г эцсийн Facebook post болгон угсрах"""
    category = translation_result.get("category", DEFAULT_CATEGORY).lower()
    if category not in CATEGORIES:
        category = DEFAULT_CATEGORY

    cat = CATEGORIES[category]
    badge = cat["badge"]

    headline = translation_result["headline"]
    body = translation_result["post_text"]
    dynamic_hashtag = translation_result.get("dynamic_hashtag", "")

    # Эцсийн постын бүтэц
    full_post = f"""{badge}

{headline}

{body}{build_footer(category, dynamic_hashtag)}"""

    return full_post, category


def translate_article(article):
    """Нэг мэдээг Claude API-р орчуулах"""

    user_prompt = f"""Дараах англи хэл дээрх мэдээг Orange News-ийн Bloomberg/Lemon Press
хэв маягаар Монгол хэлэнд шилжүүл.

=== ЭХ МЭДЭЭ ===

Гарчиг: {article.get('title', '')}

Агуулга:
{article.get('summary', '')}

Эх сурвалж: {article.get('source', 'Unknown')}
URL: {article.get('link', '')}

=== ДААЛГАВАР ===

1. 3-алхмын логикийг дагаж ажилла (ойлгох → дахин бичих → алдаа шалгах)
2. Категорийг зөв сонго
3. Динамик hashtag мэдээнээс гарга
4. AI smell үгс устгасан байх
5. Зөвхөн JSON объект буцаа (код блок, тайлбар хэрэггүй)
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=BLOOMBERG_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}]
    )

    # Хариуг parse хийх
    raw_text = response.content[0].text.strip()

    # Зарим үед Claude ```json блок дотор буцаадаг
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

    # Facebook post формат болгон угсрах
    full_post, category = format_post(result)

    return {
        "category": category,
        "badge": CATEGORIES[category]["badge"],
        "headline": result["headline"],
        "post_text": result["post_text"],
        "full_post": full_post,  # Facebook-д шууд тавих эцсийн текст
        "dynamic_hashtag": result.get("dynamic_hashtag", ""),
        "key_numbers": result.get("key_numbers", []),
        "hashtags": ["#OrangeNews"] + CATEGORIES[category]["hashtags"],
        "original_url": article.get("link", ""),
        "original_title": article.get("title", ""),
        "source": article.get("source", "Unknown"),
        "score": article.get("score", 0)
    }


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main():
    print("🟠 Orange News Translator v5 эхэлж байна...\n")

    # API key шалгах
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY environment variable олдсонгүй!")
        sys.exit(1)

    # Input файл унших
    if not os.path.exists(INPUT_FILE):
        print(f"❌ {INPUT_FILE} файл олдсонгүй!")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"📥 {len(articles)} мэдээ унших...\n")

    # Мэдээ бүрийг орчуулах
    translated = []
    for i, article in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] {article.get('title', 'Untitled')[:60]}...")

        try:
            result = translate_article(article)
            if result:
                translated.append(result)
                print(f"  ✅ {result['badge']} | {result['headline'][:60]}")
            else:
                print(f"  ⚠️ Skip хийв")
        except Exception as e:
            print(f"  ❌ Алдаа: {e}")
            continue

        print()

    # Output файл хадгалах
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    # Категори-оор хуваарилалт харуулах
    cat_counts = {}
    for post in translated:
        cat = post["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"\n{'='*60}")
    print(f"✅ Амжилттай! {len(translated)}/{len(articles)} мэдээ орчуулав")
    print(f"📁 Хадгалсан: {OUTPUT_FILE}")
    print(f"\n📊 Категорийн хуваарилалт:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        badge = CATEGORIES.get(cat, {}).get("badge", "❓")
        print(f"  {badge}: {count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
