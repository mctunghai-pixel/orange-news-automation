import os, certifi
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
"""
orange_translator.py — Orange News AI Translator & Editor
Azurise AI System | Bloomberg style + Market Watch + Image Prompts
"""

import json
import os
import anthropic
from datetime import datetime, timezone


def get_market_data() -> str:
    """Yahoo Finance-аас live тоонуудыг татна."""
    try:
        import yfinance as yf
        tickers = {
            "S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Nikkei": "^N225",
            "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD",
            "Solana": "SOL-USD", "Алт": "GC=F", "Нефть": "CL=F"
        }
        lines = []
        for name, symbol in tickers.items():
            try:
                p = yf.Ticker(symbol).fast_info.last_price
                lines.append(f"{name}: {p:,.2f}")
            except:
                pass
        return "\n".join(lines)
    except:
        return ""

import httpx as _httpx, certifi as _certifi
client = anthropic.Anthropic(http_client=_httpx.Client(verify=_certifi.where()))

# ── Config ────────────────────────────────────────────────────────────────────

INPUT_FILE  = "top_news.json"
OUTPUT_FILE = "translated_posts.json"

FOOTER = """\n\n---\n\n🌐 Вэбсайт: https://www.orangenews.mn\n📘 Facebook: https://www.facebook.com/orangenews.mn\n🧵 Threads: https://www.threads.net/@orangenews.official\n\n#OrangeNews #Finance #MarketWatch"""

# ── Bloomberg Editor Prompt ───────────────────────────────────────────────────

BLOOMBERG_SYSTEM = """Чи бол Orange News-ийн ахлах редактор. Bloomberg агентлагийн хэв маягаар мэдээ бич.

ХАТУУ ХОРИГЛОЛТ — эдгээрийг ОГТХОН бичихгүй:
- "Та үүнийг юу гэж бодож байна?" гэх мэт асуулт
- "Сэтгэгдэлээ хуваалцаарай" гэх мэт уриалга
- "Монголын хөрөнгө оруулагчдад..." гэх мэт хандалт
- "Монголд хамааралтай нь..." гэх мэт хавсарга
- "Энэ нь манай улсад..." гэх мэт дүгнэлт
- "Та үүнийг анхааралтай дагах хэрэгтэй" гэх мэт зөвлөгөө
- Эхний өгүүлбэрт асуулт тавихгүй — баримтаас шууд эхэл
- Emoji ашиглахгүй

НАЙРУУЛГЫН ДҮРЭМ:
1. Bloomberg маягаар: Хамгийн чухал баримт ЭХЭНД, дараа нь нарийвчилсан мэдээлэл.
2. Техникийн үгсийг орчуулна:
   - "Private Equity" → "хувийн хөрөнгө оруулалтын сан"
   - "Acquisition" → "худалдан авалт"
   - "Revenue" → "орлого"
   - "Merger" → "нэгдэл"
3. Тоо, хувь, компаниудын нэрийг яг үнэн зөв байлга.
4. Эх сурвалжийг төгсгөлд нэг мөрөөр дурд: "Эх сурвалж: [нэр]"
5. Нийт урт: 150-250 үг.
6. ЗӨВХӨН баримт — opinion, таамаглал, зөвлөгөө бичихгүй.

БҮТЭЦ:
[Гарчиг — товч, тодорхой, баримт дээр суурилсан]

[1-р хэсэг: Гол баримт — 1-2 өгүүлбэр, тоо баримттай]

[2-р хэсэг: Нарийвчилсан мэдээлэл — 3-4 өгүүлбэр]

[3-р хэсэг: Зах зээлийн контекст — 1-2 өгүүлбэр]

Эх сурвалж: [нэр]"""

# ── Image Prompt Generator ────────────────────────────────────────────────────

IMAGE_SYSTEM = """Чи бол Orange News брэндийн Creative Director.
Orange News өнгө: Deep Orange #FF6B35, Dark Navy #1A1A2E, Gold #FFD700.

Мэдээний агуулгад тохирсон Midjourney/DALL-E зургийн prompt бич.
Шаардлага:
- Мэргэжлийн, санхүүгийн/бизнесийн сэдэв
- Футуристик, tech-ийн мэдрэмжтэй
- Цагаан текст давхарлах зай агуулсан
- Orange болон Navy өнгөний схем
- Зөвхөн prompt текст бич, өөр юу ч бичихгүй. Англиар."""

# ── Market Watch Template ─────────────────────────────────────────────────────

MARKET_WATCH_SYSTEM = """Чи бол Orange News-ийн Market Watch редактор.
Өгөгдсөн санхүүгийн мэдээнүүдийг нэгтгэж, өглөөний Market Watch мэдээ бэлтгэ.

ЗАГВАР (яг энэ бүтцийг ашигла):

🟠 ORANGE MARKET WATCH: ({date}) 🟠

{өглөөний товч тойм — 2 өгүүлбэр}

💵 ВАЛЮТЫН ХАНШ (Монголбанк албан ханш)
🇺🇸 USD: [дүн]₮ | 🇪🇺 EUR: [дүн]₮ | 🇨🇳 CNY: [дүн]₮

🌐 ДЭЛХИЙН ХӨРӨНГИЙН ЗАХ ЗЭЭЛ
🇺🇸 S&P 500: [дүн] | Nasdaq: [дүн] | 🇯🇵 Nikkei: [дүн]

💎 КРИПТО ЗАХ ЗЭЭЛ
₿ Bitcoin: $[дүн] | Ethereum: $[дүн] | Solana: $[дүн]

🏭 ТҮҮХИЙ ЭД
🥇 Алт: $[дүн]/унц | 🛢️ Нефть: $[дүн]/баррель | 🔶 Зэс: $[дүн]/тонн

📱 ТОП КОМПАНИ (Nasdaq)
• [Компани]: $[дүн] ([өөрчлөлт])
• [Компани]: $[дүн] ([өөрчлөлт])

Эх сурвалж: Binance / Mongolbank / Nasdaq / Bloomberg

ДҮРЭМ: Тоонуудыг орчуулж өгсөн мэдээнүүдээс ав. Мэдээлэл дутуу бол тэр хэсгийг орхи."""

# ── Core Functions ────────────────────────────────────────────────────────────

def translate_bloomberg(article: dict) -> str:
    """Translate and rewrite article in Bloomberg style."""
    raw = f"Гарчиг: {article.get('title', '')}\n\nАгуулга: {article.get('content', article.get('summary', ''))}\n\nЭх сурвалж: {article.get('source', 'Reuters')}"
    
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=BLOOMBERG_SYSTEM,
        messages=[{"role": "user", "content": raw}]
    )
    return response.content[0].text.strip()


def generate_image_prompt(article_text: str) -> str:
    """Generate AI image prompt for the article."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        system=IMAGE_SYSTEM,
        messages=[{"role": "user", "content": f"Generate image prompt for this news:\n\n{article_text}"}]
    )
    return response.content[0].text.strip()


def create_market_watch(articles: list) -> str:
    """Create Market Watch post from multiple articles."""
    market_data = get_market_data()
    combined = "\n\n---\n\n".join([
        f"Гарчиг: {a.get('title','')}\nАгуулга: {a.get('content', a.get('summary',''))}"
        for a in articles[:5]
    ])
    
    today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        system=MARKET_WATCH_SYSTEM,
        messages=[{"role": "user", "content": f"Өнөөдрийн огноо: {today}\n\nLIVE ЗАХЗЭЭЛИЙН ТОО (яг эдгээрийг ашигла):\n{market_data}\n\nМэдээнүүд:\n\n{combined}"}]
    )
    return response.content[0].text.strip()


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def run():
    # Load articles
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)
    
    print(f"📰 {len(articles)} мэдээ олдлоо\n")
    
    results = []
    
    for i, article in enumerate(articles):
        print(f"[{i+1}/{len(articles)}] Боловсруулж байна: {article.get('title','')[:50]}...")
        
        is_market_watch = (i == 0)
        
        if is_market_watch:
            # Market Watch — бүх мэдээг нэгтгэж гаргана
            print("  📊 Market Watch горим...")
            post_text = create_market_watch(articles)
            image_prompt = "Orange News Market Watch dashboard, holographic financial data display, Mongolia map glowing orange, stock charts and crypto prices, dark navy background with orange accent lights, professional financial news aesthetic, Midjourney style --ar 1:1 --v 6"
            post_type = "market_watch"
        else:
            # Энгийн мэдээ — Bloomberg найруулга
            post_text = translate_bloomberg(article)
            image_prompt = generate_image_prompt(post_text)
            post_type = "news"
        
        # Footer нэмэх
        final_post = post_text + FOOTER
        
        result = {
            "index": i,
            "type": post_type,
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
            "post_text": final_post,
            "image_prompt": image_prompt,
            "use_market_watch_image": is_market_watch,
            "headline": post_text.split("\n")[0][:80],
        }
        
        results.append(result)
        print(f"  ✅ Дууслаа | Type: {post_type}")
        
        # Зөвхөн Market Watch мэдээг үүсгэнэ — бусад мэдээ энгийн
        if is_market_watch:
            print("  ⏭️  Market Watch үүслээ — бусад мэдээг дараах алхамд боловсруулна\n")
            break  # Нэг Market Watch хангалттай, бусдыг fb_poster боловсруулна
    
    # Үлдсэн мэдээнүүдийг Bloomberg найруулгаар нэмнэ
    for i, article in enumerate(articles[1:], start=1):
        print(f"[{i+1}/{len(articles)}] Мэдээ боловсруулж байна: {article.get('title','')[:50]}...")
        post_text = translate_bloomberg(article)
        image_prompt = generate_image_prompt(post_text)
        final_post = post_text + FOOTER
        
        result = {
            "index": i,
            "type": "news",
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
            "post_text": final_post,
            "image_prompt": image_prompt,
            "use_market_watch_image": False,
            "headline": post_text.split("\n")[0][:80],
        }
        results.append(result)
        print(f"  ✅ Дууслаа")
    
    # Хадгалах
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ {len(results)} пост хадгалагдлаа → {OUTPUT_FILE}")
    print(f"📊 Market Watch: 1 | 📰 Мэдээ: {len(results)-1}")


if __name__ == "__main__":
    run()
