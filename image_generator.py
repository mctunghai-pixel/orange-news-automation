"""
image_generator.py — Orange News Visual Generator v3
Azurise AI System

Fixes v3:
  1. ✅ Markdown ** ## # тэмдэглэгээ + "Та үүнийг..." хиймэл төгсгөл цэвэрлэнэ
  2. ✅ Logo зүүн доод буланд headline-тай ОГТХОН давхцахгүй (fixed layout)
  3. ✅ OG зураг татагдахгүй үед илүү мэргэжлийн gradient background
  4. ✅ translated_posts.json болон translated_posts_v2.json аль алиныг дэмжинэ
"""

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import requests, os, re, textwrap
from io import BytesIO
from datetime import datetime
from urllib.parse import urljoin
from html.parser import HTMLParser

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "assets/generated"
LOGO_PATH  = "assets/logo.png"
IMG_W, IMG_H = 1200, 630

COLOR_ORANGE = (255, 107, 53)
COLOR_WHITE  = (255, 255, 255)
COLOR_GRAY   = (160, 160, 160)

CATEGORY_COLORS = {
    "FINANCE":  (255, 107, 53),
    "AI":       (80,  180, 255),
    "TECH":     (100, 220, 120),
    "CRYPTO":   (255, 200,   0),
    "ECONOMY":  (255, 107,  53),
    "DEFAULT":  (255, 107,  53),
}

CATEGORY_GRADIENT = {
    "FINANCE":  ((18, 18, 35), (35, 18,  8)),
    "AI":       (( 8, 18, 38), (18,  8, 38)),
    "TECH":     (( 8, 28, 18), (18, 28,  8)),
    "CRYPTO":   ((28, 22,  4), (18, 18, 35)),
    "DEFAULT":  ((18, 18, 35), (12, 12, 25)),
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Font ──────────────────────────────────────────────────────────────────────
def get_font(size, bold=False):
    paths = [
        # Ubuntu/Linux — Noto фонт (Монгол дэмжинэ)
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold
            else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansMongolian-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()


# ── Text cleaner ──────────────────────────────────────────────────────────────
def clean_headline(text: str) -> str:
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"_{2,}", "", text)
    # Хиймэл төгсгөл хэллэг
    for pattern in [
        r"Та үүнийг юу гэж бодож байна\?.*",
        r"Сэтгэгдэлээ хуваалцаарай.*",
        r"Монголын хөрөнгө оруулагчдад.*",
        r"👇.*",
    ]:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)
    first = text.strip().split("\n")[0].strip()
    return (first[:88] + "…") if len(first) > 90 else first


def extract_headline(post: dict) -> str:
    h = post.get("headline", "")
    if h and len(h) > 5:
        return clean_headline(h)
    pt = post.get("post_text", "")
    if pt:
        return clean_headline(pt)
    return clean_headline(post.get("title", post.get("original_title", "")))


def get_article_url(post: dict) -> str:
    return post.get("url") or post.get("original_url") or ""


# ── OG image fetcher ──────────────────────────────────────────────────────────
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
    if not article_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
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
        print(f"    🖼️  OG зураг: {img_url[:65]}...")
        return img
    except Exception as e:
        print(f"    ⚠️  OG татаж чадсангүй: {e}")
        return None


# ── Gradient background ───────────────────────────────────────────────────────
def make_gradient_bg(category: str) -> Image.Image:
    stops = CATEGORY_GRADIENT.get(category.upper(), CATEGORY_GRADIENT["DEFAULT"])
    c1, c2 = stops
    base = Image.new("RGB", (IMG_W, IMG_H))
    draw = ImageDraw.Draw(base)
    for y in range(IMG_H):
        t = y / IMG_H
        draw.line([(0, y), (IMG_W, y)], fill=(
            int(c1[0] + (c2[0]-c1[0])*t),
            int(c1[1] + (c2[1]-c1[1])*t),
            int(c1[2] + (c2[2]-c1[2])*t),
        ))
    # Dot grid overlay
    ov = Image.new("RGBA", (IMG_W, IMG_H), (0,0,0,0))
    od = ImageDraw.Draw(ov)
    for x in range(0, IMG_W, 60):
        for y in range(0, IMG_H, 60):
            od.ellipse([(x-1,y-1),(x+1,y+1)], fill=(255,255,255,18))
    # Diagonal glow
    accent = CATEGORY_COLORS.get(category.upper(), COLOR_ORANGE)
    for i in range(3):
        od.line([(int(IMG_W*0.55)+i*3, 0),(int(IMG_W*1.1)+i*3, IMG_H)],
                fill=(*accent, 22), width=55)
    return Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")


# ── Main generator ────────────────────────────────────────────────────────────
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
    ├────────────────────────────────────────┤ ← separator line
    │ [LOGO]  orangenews.mn                  │ BOTTOM_BAR (48px)
    └────────────────────────────────────────┘
    """
    headline  = clean_headline(headline)
    cat_upper = category.upper()
    accent    = CATEGORY_COLORS.get(cat_upper, CATEGORY_COLORS["DEFAULT"])

    # 1. Background
    bg_img = None
    if image_url:
        try:
            r = requests.get(image_url, timeout=8)
            bg_img = Image.open(BytesIO(r.content)).convert("RGB")
        except: pass
    if bg_img is None and article_url:
        bg_img = fetch_og_image(article_url)

    if bg_img is None:
        print(f"    🎨 Gradient ({cat_upper})")
        base = make_gradient_bg(cat_upper)
    else:
        base = bg_img.resize((IMG_W, IMG_H), Image.LANCZOS)
        base = ImageEnhance.Brightness(base).enhance(0.55)
        base = base.filter(ImageFilter.GaussianBlur(radius=1.2))

    # 2. Bottom shadow
    ov = Image.new("RGBA", (IMG_W, IMG_H), (0,0,0,0))
    od = ImageDraw.Draw(ov)
    grad_start = int(IMG_H * 0.38)
    for y in range(grad_start, IMG_H):
        t = (y - grad_start) / (IMG_H - grad_start)
        od.line([(0,y),(IMG_W,y)], fill=(8, 8, 18, int(248 * t**0.7)))
    base = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(base)

    # 3. Accent bars
    draw.rectangle([(0,0),(6,IMG_H)], fill=accent)
    draw.rectangle([(0,0),(IMG_W,5)], fill=accent)

    # 4. Category badge
    cat_font  = get_font(19, bold=True)
    badge_pad = 14
    bbox      = draw.textbbox((0,0), cat_upper, font=cat_font)
    bw        = bbox[2] - bbox[0] + badge_pad*2
    draw.rectangle([(22,22),(22+bw, 22+30)], fill=accent)
    draw.text((22+badge_pad, 27), cat_upper, font=cat_font, fill=COLOR_WHITE)

    # 5. HEADLINE — fixed bottom-up layout
    BOTTOM_BAR = 50   # Logo + watermark zone
    LINE_H     = 70
    h_font     = get_font(58, bold=True)
    wrapped    = textwrap.wrap(headline, width=30)[:3]

    # Мөрүүдийг доороос дээшээ байрлуулна
    for i, line in enumerate(reversed(wrapped)):
        y = IMG_H - BOTTOM_BAR - 12 - (i * LINE_H) - LINE_H + 10
        draw.text((32, y+2), line, font=h_font, fill=(0,0,0))   # shadow
        draw.text((30, y),   line, font=h_font, fill=COLOR_WHITE)

    # 6. Separator line
    sep_y = IMG_H - BOTTOM_BAR
    draw.line([(22, sep_y),(IMG_W-22, sep_y)], fill=(*accent, 120), width=1)

    # 7. Logo + watermark (bottom bar дотор — headline-аас ДООР)
    LOGO_H  = 30
    logo_y  = IMG_H - LOGO_H - 10
    wm_x    = 22
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw   = int(logo.width * LOGO_H / logo.height)
        logo = logo.resize((lw, LOGO_H), Image.LANCZOS)
        base.paste(logo, (22, logo_y), logo)
        wm_x = 22 + lw + 10
    except:
        pass

    draw.text((wm_x, logo_y + 7), "orangenews.mn", font=get_font(16), fill=COLOR_GRAY)

    # 8. Save
    today = datetime.now().strftime("%Y%m%d")
    out   = f"{OUTPUT_DIR}/post_{index:02d}_{today}.png"
    base.save(out, "PNG", quality=95)
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("🎨 Orange News Image Generator v3")
    print("=" * 50)

    json_file = None
    for c in ["translated_posts_v2.json", "translated_posts.json", "top_news.json"]:
        if os.path.exists(c):
            json_file = c
            break

    if not json_file:
        path = generate_image("Apple компани эхний улирлын орлогоо зарлалаа", "TECH", index=0)
        print(f"✅ Тест: {path}")
    else:
        with open(json_file, "r", encoding="utf-8") as f:
            posts = json.load(f)
        print(f"📂 {json_file} → {len(posts)} пост\n")
        for i, p in enumerate(posts):
            ptype = (p.get("type","") or p.get("category","")).lower()
            if "market_watch" in ptype:
                print(f"  [{i:02d}] ⏭️  Market Watch алгасав")
                continue
            headline    = extract_headline(p)
            category    = p.get("category", "FINANCE")
            img_url     = p.get("image_url","")
            article_url = get_article_url(p)
            print(f"  [{i:02d}] {headline[:55]}...")
            path = generate_image(headline=headline, category=category,
                                  image_url=img_url, article_url=article_url, index=i)
            print(f"       ✅ {os.path.basename(path)}")

    print("\n🍊 Дууслаа!")
