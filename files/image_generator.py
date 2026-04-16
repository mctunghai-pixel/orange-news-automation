"""
image_generator.py — Orange News Visual Generator v2
Azurise AI System

Fixes v2:
  1. Logo + Headline давхцах асуудал засагдлаа
     → Logo доод баруун буланд шилжлээ (headline-тай зөрчилдөхгүй)
  2. Article URL-аас OG/meta зураг автоматаар татна
     → Зураг олдохгүй бол category-д тохирсон gradient background ашиглана
  3. Headline дээрх ** markdown тэмдэглэгээ цэвэрлэнэ
  4. Category-д тохирсон accent өнгө
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import requests, os, re, textwrap
from io import BytesIO
from datetime import datetime
from urllib.parse import urljoin
from html.parser import HTMLParser

# ── Paths & Constants ─────────────────────────────────────────────────────────
ASSETS_DIR = "assets"
OUTPUT_DIR = "assets/generated"
LOGO_PATH  = "assets/logo.png"

COLOR_ORANGE = (255, 107, 53)
COLOR_BG     = (26, 26, 46)
COLOR_WHITE  = (255, 255, 255)
COLOR_GRAY   = (180, 180, 180)
COLOR_GOLD   = (255, 215, 0)

IMG_W, IMG_H = 1200, 630

# Category-д тохирсон accent өнгө
CATEGORY_COLORS = {
    "FINANCE":  (255, 107, 53),   # Orange
    "AI":       (100, 200, 255),  # Cyan-blue
    "TECH":     (120, 220, 120),  # Green
    "CRYPTO":   (255, 215, 0),    # Gold
    "ECONOMY":  (255, 107, 53),   # Orange
    "DEFAULT":  (255, 107, 53),
}

# Category-д тохирсон background gradient өнгө (зураг олдохгүй үед)
CATEGORY_BG = {
    "FINANCE":  [(26, 26, 46), (40, 20, 10)],
    "AI":       [(10, 20, 40), (20, 10, 40)],
    "TECH":     [(10, 30, 20), (20, 30, 10)],
    "CRYPTO":   [(30, 25, 5),  (20, 20, 40)],
    "DEFAULT":  [(26, 26, 46), (15, 15, 30)],
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Font loader ───────────────────────────────────────────────────────────────
def get_font(size, bold=False):
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ── OG Image fetcher ──────────────────────────────────────────────────────────
class OGParser(HTMLParser):
    """Extract og:image from HTML <meta> tags."""
    def __init__(self):
        super().__init__()
        self.og_image = None

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.og_image:
            d = dict(attrs)
            if d.get("property") == "og:image" or d.get("name") == "twitter:image":
                self.og_image = d.get("content", "")


def fetch_og_image(article_url: str) -> "Image.Image | None":
    """
    Мэдээний URL-аас og:image татна.
    Амжилтгүй бол None буцаана.
    """
    if not article_url:
        return None
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(article_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None

        parser = OGParser()
        parser.feed(r.text[:50000])  # Зөвхөн эхний 50KB уншна

        img_url = parser.og_image
        if not img_url:
            return None

        # Relative URL → absolute
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            img_url = urljoin(article_url, img_url)

        img_r = requests.get(img_url, headers=headers, timeout=8)
        img = Image.open(BytesIO(img_r.content)).convert("RGB")
        print(f"    🖼️  OG зураг олдлоо: {img_url[:70]}...")
        return img

    except Exception as e:
        print(f"    ⚠️  OG зураг татаж чадсангүй: {e}")
        return None


def fetch_image(url: str) -> "Image.Image | None":
    """Direct image URL-аас зураг татна."""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=8)
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


# ── Gradient background (зураг байхгүй үед) ──────────────────────────────────
def make_gradient_bg(category: str) -> Image.Image:
    """Category-д тохирсон gradient background үүсгэнэ."""
    colors = CATEGORY_BG.get(category.upper(), CATEGORY_BG["DEFAULT"])
    c1, c2 = colors[0], colors[1]

    base = Image.new("RGB", (IMG_W, IMG_H), c1)
    draw = ImageDraw.Draw(base)

    # Diagonal gradient effect
    for y in range(IMG_H):
        t = y / IMG_H
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (IMG_W, y)], fill=(r, g, b))

    # Subtle grid lines (финансийн мэдрэмж)
    grid_color = (255, 255, 255, 12)
    overlay = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for x in range(0, IMG_W, 80):
        od.line([(x, 0), (x, IMG_H)], fill=grid_color, width=1)
    for y in range(0, IMG_H, 80):
        od.line([(0, y), (IMG_W, y)], fill=grid_color, width=1)
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    return base


# ── Text cleaner ──────────────────────────────────────────────────────────────
def clean_headline(text: str) -> str:
    """Markdown тэмдэглэгээ болон хэт урт текстийг цэвэрлэнэ."""
    text = re.sub(r"\*+", "", text)          # ** bold markers
    text = re.sub(r"#+\s*", "", text)        # ## headers
    text = re.sub(r"`+", "", text)           # backticks
    text = text.strip()
    return text


# ── Main generator ────────────────────────────────────────────────────────────
def generate_image(
    headline: str,
    category: str = "FINANCE",
    image_url: str = None,
    article_url: str = None,
    index: int = 0,
) -> str:
    """
    Нэг мэдээний зураг үүсгэнэ.

    Args:
        headline:    Мэдээний гарчиг (Markdown цэвэрлэгдэнэ)
        category:    FINANCE | AI | TECH | CRYPTO | ECONOMY
        image_url:   Шууд зургийн URL (optional)
        article_url: Мэдээний хуудасны URL — OG зураг татахад ашиглана
        index:       Файлын дугаар
    Returns:
        Хадгалагдсан файлын path
    """
    headline = clean_headline(headline)
    cat_upper = category.upper()
    accent_color = CATEGORY_COLORS.get(cat_upper, CATEGORY_COLORS["DEFAULT"])

    # ── 1. Background зураг авах ──────────────────────────────────────────────
    bg_img = None

    # Priority 1: Шууд зургийн URL
    if image_url:
        bg_img = fetch_image(image_url)

    # Priority 2: Article OG image
    if bg_img is None and article_url:
        bg_img = fetch_og_image(article_url)

    # Priority 3: Gradient background
    if bg_img is None:
        print(f"    🎨 Gradient background ашиглаж байна ({cat_upper})")
        base = make_gradient_bg(cat_upper)
    else:
        base = bg_img.resize((IMG_W, IMG_H), Image.LANCZOS)
        # Зураг харлуулах + slight blur
        base = ImageEnhance.Brightness(base).enhance(0.40)
        base = base.filter(ImageFilter.GaussianBlur(radius=1.5))

    # ── 2. Bottom gradient overlay (текст уншигдахуйц болгох) ────────────────
    overlay = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)

    # Доод 60% — gradient shadow
    grad_start = int(IMG_H * 0.35)
    for y in range(grad_start, IMG_H):
        t = (y - grad_start) / (IMG_H - grad_start)
        alpha = int(230 * (t ** 0.8))
        ov_draw.line([(0, y), (IMG_W, y)], fill=(10, 10, 20, alpha))

    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── 3. Orange accent bars ─────────────────────────────────────────────────
    draw.rectangle([(0, 0), (6, IMG_H)], fill=accent_color)       # Зүүн
    draw.rectangle([(0, 0), (IMG_W, 5)], fill=accent_color)       # Дээд

    # ── 4. Category badge ─────────────────────────────────────────────────────
    cat_font = get_font(20, bold=True)
    badge_text = cat_upper
    badge_pad = 16
    bbox = draw.textbbox((0, 0), badge_text, font=cat_font)
    badge_w = bbox[2] - bbox[0] + badge_pad * 2
    badge_h = 34

    bx, by = 30, 30
    draw.rectangle([(bx, by), (bx + badge_w, by + badge_h)], fill=accent_color)
    draw.text((bx + badge_pad, by + 7), badge_text, font=cat_font, fill=COLOR_WHITE)

    # ── 5. Headline text ──────────────────────────────────────────────────────
    # Logo height = 42px, bottom margin = 18px → logo top = IMG_H - 60
    # Headline must end above logo: leave 80px clearance from bottom
    h_font = get_font(52, bold=True)
    sm_font = get_font(38, bold=True)

    wrapped = textwrap.wrap(headline, width=28)[:3]

    # Text block байрлал — доороос дээшээ
    # Logo + bottom bar = 75px → headline block ends at IMG_H - 85
    line_h = 62
    block_h = len(wrapped) * line_h
    text_y_start = IMG_H - 85 - block_h

    # Ensure it doesn't go too high
    text_y_start = max(text_y_start, int(IMG_H * 0.45))

    for i, line in enumerate(wrapped):
        y = text_y_start + i * line_h
        # Shadow
        draw.text((32, y + 2), line, font=h_font, fill=(0, 0, 0))
        # Main text
        draw.text((30, y), line, font=h_font, fill=COLOR_WHITE)

    # ── 6. Logo — доод БАРУУН БУЛАНД (headline-тай зөрчилдөхгүй) ────────────
    LOGO_H = 38
    logo_placed = False
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = int(logo.width * LOGO_H / logo.height)
        logo = logo.resize((lw, LOGO_H), Image.LANCZOS)

        # Байрлал: доод баруун — orangenews.mn текстийн дээгүүр
        logo_x = IMG_W - lw - 20
        logo_y = IMG_H - LOGO_H - 15
        base.paste(logo, (logo_x, logo_y), logo)
        logo_placed = True
    except Exception:
        pass

    if not logo_placed:
        draw.text(
            (IMG_W - 180, IMG_H - 45),
            "OrangeNews.mn",
            font=get_font(20, bold=True),
            fill=accent_color,
        )

    # ── 7. orangenews.mn watermark (доод зүүн) ───────────────────────────────
    draw.text((22, IMG_H - 32), "orangenews.mn", font=get_font(18), fill=COLOR_GRAY)

    # ── 8. Хадгалах ──────────────────────────────────────────────────────────
    out = f"{OUTPUT_DIR}/post_{index:02d}_{datetime.now().strftime('%Y%m%d')}.png"
    base.save(out, "PNG", quality=95)
    return out


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("🎨 Orange News Image Generator v2")
    print("=" * 50)

    # Тест зураг
    path = generate_image(
        headline="Apple компани эхний улирлын орлогоо зарлалаа",
        category="TECH",
        article_url=None,
        index=0,
    )
    print(f"✅ Тест зураг: {path}\n")

    # translated_posts.json байгаа бол бүх зургийг үүсгэнэ
    json_file = "translated_posts.json"
    if not os.path.exists(json_file):
        json_file = "top_news.json"

    if os.path.exists(json_file):
        with open(json_file, "r", encoding="utf-8") as f:
            posts = json.load(f)

        print(f"📰 {len(posts)} пост олдлоо → зурагнууд үүсгэж байна...\n")

        for i, p in enumerate(posts):
            if p.get("type") == "market_watch" or p.get("category") == "market_watch":
                print(f"  [{i:02d}] ⏭️  Market Watch — зураг алгасав")
                continue

            headline = p.get("headline") or p.get("title", "")
            category = p.get("category", "FINANCE").upper()
            img_url  = p.get("image_url", "")
            art_url  = p.get("url", "")

            print(f"  [{i:02d}] {headline[:55]}...")
            path = generate_image(
                headline=headline,
                category=category,
                image_url=img_url,
                article_url=art_url,
                index=i,
            )
            print(f"       ✅ {path}")

    print("\n🍊 Дууслаа!")
