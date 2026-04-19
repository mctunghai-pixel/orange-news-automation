"""
Orange News — Image Generator v7 FINAL
=======================================
Бүх засвар нэгтгэсэн эцсийн хувилбар

Шинэчлэлт:
1. ✅ 7 категори (6 news + market_watch)
2. ✅ Fixed layout (headline + logo огтхон давхцалгүй)
3. ✅ OG зураг татагдахгүй үед category gradient
4. ✅ Market Watch-д тусгай layout
5. ✅ fb_poster.py-ээс generate_image() функц дуудах боломжтой
6. ✅ Markdown # ** ## тэмдэгтийг цэвэрлэнэ
7. ✅ URL талбар зөв уншина (url болон original_url)
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import requests, os, re, textwrap, platform, json
from io import BytesIO
from datetime import datetime
from urllib.parse import urljoin
from html.parser import HTMLParser

# =============================================================================
# CONFIG
# =============================================================================

OUTPUT_DIR = "assets/generated"
LOGO_PATH = "assets/logo.png"
IMG_W, IMG_H = 1200, 630

COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (160, 160, 160)

# 7 категори — badge text, өнгө, gradient
CATEGORIES = {
    "FINANCE": {
        "badge": "🔶 FINANCE",
        "accent": (255, 107, 26),       # Orange
        "gradient": ((120, 40, 10), (20, 10, 5)),
    },
    "TECH": {
        "badge": "🔷 TECH",
        "accent": (30, 144, 255),       # Blue
        "gradient": ((10, 40, 120), (5, 10, 30)),
    },
    "CRYPTO": {
        "badge": "🟡 CRYPTO",
        "accent": (240, 185, 11),       # Yellow
        "gradient": ((120, 90, 5), (30, 20, 5)),
    },
    "AI": {
        "badge": "🟣 AI",
        "accent": (155, 89, 182),       # Purple
        "gradient": ((70, 30, 100), (20, 10, 30)),
    },
    "BUSINESS": {
        "badge": "🟠 BUSINESS",
        "accent": (230, 126, 34),       # Dark orange
        "gradient": ((110, 55, 15), (25, 15, 5)),
    },
    "ECONOMY": {
        "badge": "🟢 ECONOMY",
        "accent": (39, 174, 96),        # Green
        "gradient": ((15, 80, 45), (5, 20, 10)),
    },
    "MARKET_WATCH": {
        "badge": "📊 ORANGE MARKET WATCH",
        "accent": (255, 107, 26),
        "gradient": ((130, 60, 20), (15, 8, 5)),
    },
    "DEFAULT": {
        "badge": "🟠 ORANGE NEWS",
        "accent": (255, 107, 26),
        "gradient": ((60, 30, 15), (15, 8, 5)),
    }
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


# =============================================================================
# FONT
# =============================================================================

IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

def get_font(size, bold=False):
    """Platform-аар фонт сонгох"""
    paths = []
    if IS_MACOS:
        paths = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        ]
    elif IS_LINUX:
        paths = [
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold
                else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                pass
    return ImageFont.load_default()


# =============================================================================
# TEXT CLEANER
# =============================================================================

def clean_headline(text: str) -> str:
    """Markdown, хиймэл үгсийг цэвэрлэх"""
    if not text:
        return ""

    # Markdown устгах
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"_{2,}", "", text)

    # Хиймэл төгсгөл
    for pattern in [
        r"Та үүнийг юу гэж бодож байна\?.*",
        r"Сэтгэгдэлээ хуваалцаарай.*",
        r"Монголын хөрөнгө оруулагчдад.*",
        r"Монголд хамааралтай нь.*",
        r"👇.*",
    ]:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

    first = text.strip().split("\n")[0].strip()
    return (first[:88] + "…") if len(first) > 90 else first


def extract_headline(post: dict) -> str:
    """Пост-ын гарчгийг олох"""
    h = post.get("headline", "")
    if h and len(h) > 5:
        return clean_headline(h)
    pt = post.get("post_text", "")
    if pt:
        return clean_headline(pt)
    return clean_headline(post.get("title", post.get("original_title", "")))


def get_article_url(post: dict) -> str:
    """Пост-ын URL олох — олон талбар дэмжинэ"""
    return post.get("url") or post.get("original_url") or ""


# =============================================================================
# OG IMAGE FETCHER
# =============================================================================

class OGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og_image = None

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.og_image:
            d = dict(attrs)
            if d.get("property") == "og:image" or d.get("name") == "twitter:image":
                self.og_image = d.get("content", "")


def fetch_og_image(article_url: str):
    """URL-ээс og:image татах"""
    if not article_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
        r = requests.get(article_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
        parser = OGParser()
        parser.feed(r.text[:60000])
        img_url = parser.og_image
        if not img_url:
            return None
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            img_url = urljoin(article_url, img_url)

        ir = requests.get(img_url, headers=headers, timeout=8)
        img = Image.open(BytesIO(ir.content)).convert("RGB")
        print(f"    🖼️  OG: {img_url[:65]}...")
        return img
    except Exception as e:
        print(f"    ⚠️  OG татаж чадсангүй: {e}")
        return None


# =============================================================================
# BACKGROUND
# =============================================================================

def make_gradient_bg(category: str) -> Image.Image:
    """Gradient background үүсгэх"""
    cfg = CATEGORIES.get(category.upper(), CATEGORIES["DEFAULT"])
    c1, c2 = cfg["gradient"]

    base = Image.new("RGB", (IMG_W, IMG_H))
    draw = ImageDraw.Draw(base)
    for y in range(IMG_H):
        t = y / IMG_H
        draw.line([(0, y), (IMG_W, y)], fill=(
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
        ))

    # Dot grid overlay
    ov = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for x in range(0, IMG_W, 60):
        for y in range(0, IMG_H, 60):
            od.ellipse([(x - 1, y - 1), (x + 1, y + 1)], fill=(255, 255, 255, 18))

    # Diagonal glow
    accent = cfg["accent"]
    for i in range(3):
        od.line([(int(IMG_W * 0.55) + i * 3, 0), (int(IMG_W * 1.1) + i * 3, IMG_H)],
                fill=(*accent, 22), width=55)

    return Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")


# =============================================================================
# MAIN GENERATOR
# =============================================================================

def generate_image(
    headline: str,
    category: str = "FINANCE",
    image_url: str = None,
    article_url: str = None,
    index: int = 0,
) -> str:
    """
    FIXED LAYOUT (давхцалгүй):
    ┌────────────────────────────────────────┐
    │ [BADGE]                                │ y=22
    │                                        │
    │            [BACKGROUND]                │
    │                                        │
    │ Headline мөр 1                         │
    │ Headline мөр 2                         │
    │ Headline мөр 3          (max 3 мөр)    │
    ├────────────────────────────────────────┤ ← separator
    │ [LOGO]  orangenews.mn                  │ BOTTOM_BAR (50px)
    └────────────────────────────────────────┘
    """
    headline = clean_headline(headline)
    cat_upper = category.upper() if category else "DEFAULT"
    if cat_upper not in CATEGORIES:
        cat_upper = "DEFAULT"

    cfg = CATEGORIES[cat_upper]
    accent = cfg["accent"]
    badge_text = cfg["badge"]

    # 1. Background
    bg_img = None
    if image_url:
        try:
            r = requests.get(image_url, timeout=8)
            bg_img = Image.open(BytesIO(r.content)).convert("RGB")
        except:
            pass
    if bg_img is None and article_url:
        bg_img = fetch_og_image(article_url)

    if bg_img is None:
        print(f"    🎨 Gradient ({cat_upper})")
        base = make_gradient_bg(cat_upper)
    else:
        base = bg_img.resize((IMG_W, IMG_H), Image.LANCZOS)
        base = ImageEnhance.Brightness(base).enhance(0.38)
        base = base.filter(ImageFilter.GaussianBlur(radius=1.2))

    # 2. Bottom shadow
    ov = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    grad_start = int(IMG_H * 0.38)
    for y in range(grad_start, IMG_H):
        t = (y - grad_start) / (IMG_H - grad_start)
        od.line([(0, y), (IMG_W, y)], fill=(8, 8, 18, int(248 * t ** 0.7)))
    base = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(base)

    # 3. Accent bars
    draw.rectangle([(0, 0), (6, IMG_H)], fill=accent)
    draw.rectangle([(0, 0), (IMG_W, 5)], fill=accent)

    # 4. Badge — mobile safe-zone (FB mobile crops top ~8%)
    cat_font = get_font(19, bold=True)
    badge_pad = 14
    bbox = draw.textbbox((0, 0), badge_text, font=cat_font)
    bw = bbox[2] - bbox[0] + badge_pad * 2
    BADGE_Y = 55  # was 22 — moved down to avoid mobile crop
    draw.rectangle([(22, BADGE_Y), (22 + bw, BADGE_Y + 30)], fill=accent)
    draw.text((22 + badge_pad, BADGE_Y + 5), badge_text, font=cat_font, fill=COLOR_WHITE)

    # 5. HEADLINE — fixed bottom-up layout
    BOTTOM_BAR = 50
    LINE_H = 62
    h_font = get_font(50, bold=True)
    wrapped = textwrap.wrap(headline, width=30)[:3]

    # Доороос дээш
    for i, line in enumerate(reversed(wrapped)):
        y = IMG_H - BOTTOM_BAR - 12 - (i * LINE_H) - LINE_H + 10
        draw.text((32, y + 2), line, font=h_font, fill=(0, 0, 0))  # shadow
        draw.text((30, y), line, font=h_font, fill=COLOR_WHITE)

    # 6. Separator
    sep_y = IMG_H - BOTTOM_BAR
    draw.line([(22, sep_y), (IMG_W - 22, sep_y)], fill=(*accent, 120), width=1)

    # 7. Logo + watermark
    LOGO_H = 30
    logo_y = IMG_H - LOGO_H - 10
    wm_x = 22
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = int(logo.width * LOGO_H / logo.height)
        logo = logo.resize((lw, LOGO_H), Image.LANCZOS)
        base.paste(logo, (22, logo_y), logo)
        wm_x = 22 + lw + 10
    except:
        pass

    draw.text((wm_x, logo_y + 7), "orangenews.mn", font=get_font(16), fill=COLOR_GRAY)

    # 8. Save
    today = datetime.now().strftime("%Y%m%d")
    out = f"{OUTPUT_DIR}/post_{index:02d}_{today}.png"
    base.save(out, "PNG", quality=95)
    return out


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("🎨 Orange News Image Generator v7 FINAL")
    print("=" * 50)

    # JSON эх үүсвэрийг хайх (priority order)
    json_file = None
    for c in ["translated_posts.json", "translated_posts_v2.json", "top_news.json"]:
        if os.path.exists(c):
            json_file = c
            break

    if not json_file:
        # Тест үүсгэх
        path = generate_image("Apple компани эхний улирлын орлогоо зарлалаа", "TECH", index=0)
        print(f"✅ Тест: {path}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        posts = json.load(f)

    print(f"📂 {json_file} → {len(posts)} пост\n")

    success = failed = 0
    for i, p in enumerate(posts):
        # Market Watch шалгах
        is_mw = (p.get("use_market_watch_image", False) or
                 p.get("type") == "market_watch" or
                 p.get("category") == "market_watch")

        category = "MARKET_WATCH" if is_mw else p.get("category", "FINANCE")
        headline = extract_headline(p)
        img_url = p.get("image_url", "")
        article_url = get_article_url(p)

        print(f"  [{i:02d}] {headline[:55]}...")
        try:
            path = generate_image(
                headline=headline, category=category,
                image_url=img_url, article_url=article_url, index=i
            )
            # JSON-д image_path нэмэх
            p["image_path"] = path
            print(f"       ✅ {os.path.basename(path)}")
            success += 1
        except Exception as e:
            print(f"       ❌ Алдаа: {e}")
            failed += 1

    # JSON-г шинэчлэх (image_path нэмсэн)
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ Амжилттай: {success}/{len(posts)}")
    if failed:
        print(f"⚠️  Амжилтгүй: {failed}")
    print(f"📁 {OUTPUT_DIR}")
    print("🍊 Дууслаа!")


if __name__ == "__main__":
    main()
