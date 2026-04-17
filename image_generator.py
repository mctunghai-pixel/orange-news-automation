"""
Orange News — Image Generator v5
=================================
Шинэчлэлт:
1. 6 категори тус бүрт өөр badge + өнгө
2. Зөв категори автоматаар татна (translated_posts.json-оос)
3. OG зураг + gradient fallback
4. Монгол Noto фонт
5. Logo/headline давхцалгүй

Author: Azurise AI Master Architect
Date: April 2026
"""

import os
import json
import platform
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import requests
from io import BytesIO
import re

# =============================================================================
# ТОХИРГОО
# =============================================================================

INPUT_FILE = "translated_posts.json"
OUTPUT_DIR = Path("assets/generated")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Зургийн хэмжээ (Facebook/Instagram-д оновчтой)
WIDTH = 1200
HEIGHT = 630

# Font file-ийн зам (OS-ээс хамаарна)
IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

if IS_LINUX:
    FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
    FONT_REGULAR = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
elif IS_MACOS:
    FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
else:
    FONT_BOLD = "arial.ttf"
    FONT_REGULAR = "arial.ttf"

# Font size
FONT_SIZE_HEADLINE = 58
FONT_SIZE_BADGE = 22
FONT_SIZE_FOOTER = 20

# Background brightness (OG зураг хэт гэрэлтэй үед)
BG_BRIGHTNESS = 0.55

# =============================================================================
# КАТЕГОРИЙН ӨНГӨНИЙ ТОХИРГОО
# =============================================================================

CATEGORY_STYLES = {
    "finance": {
        "badge_text": "🔶 FINANCE",
        "badge_bg": (255, 107, 26),       # Orange #FF6B1A
        "badge_fg": (255, 255, 255),
        "gradient_from": (120, 40, 10),
        "gradient_to": (20, 10, 5),
    },
    "tech": {
        "badge_text": "🔷 TECH",
        "badge_bg": (30, 144, 255),       # Blue #1E90FF
        "badge_fg": (255, 255, 255),
        "gradient_from": (10, 40, 120),
        "gradient_to": (5, 10, 30),
    },
    "crypto": {
        "badge_text": "🟡 CRYPTO",
        "badge_bg": (240, 185, 11),       # Yellow #F0B90B
        "badge_fg": (30, 30, 30),
        "gradient_from": (120, 90, 5),
        "gradient_to": (30, 20, 5),
    },
    "AI": {
        "badge_text": "🟣 AI",
        "badge_bg": (155, 89, 182),       # Purple #9B59B6
        "badge_fg": (255, 255, 255),
        "gradient_from": (70, 30, 100),
        "gradient_to": (20, 10, 30),
    },
    "business": {
        "badge_text": "🟠 BUSINESS",
        "badge_bg": (230, 126, 34),       # Dark orange #E67E22
        "badge_fg": (255, 255, 255),
        "gradient_from": (110, 55, 15),
        "gradient_to": (25, 15, 5),
    },
    "economy": {
        "badge_text": "🟢 ECONOMY",
        "badge_bg": (39, 174, 96),        # Green #27AE60
        "badge_fg": (255, 255, 255),
        "gradient_from": (15, 80, 45),
        "gradient_to": (5, 20, 10),
    }
}

DEFAULT_CATEGORY = "business"

# =============================================================================
# ТУСЛАХ ФУНКЦ
# =============================================================================

def fetch_og_image(url):
    """URL-ээс og:image meta tag татаж зургийг буулгах"""
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Orange News Bot)"
        })
        html = r.text

        # og:image олох
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if not match:
            match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                html, re.IGNORECASE
            )

        if match:
            img_url = match.group(1)
            img_response = requests.get(img_url, timeout=10)
            return Image.open(BytesIO(img_response.content)).convert("RGB")
    except Exception as e:
        print(f"  ⚠️ OG зураг татаж чадсангүй: {e}")
    return None


def create_gradient(from_color, to_color, size):
    """Хоёр өнгийн хооронд босоо gradient үүсгэх"""
    w, h = size
    img = Image.new("RGB", size)
    pixels = img.load()

    for y in range(h):
        ratio = y / h
        r = int(from_color[0] * (1 - ratio) + to_color[0] * ratio)
        g = int(from_color[1] * (1 - ratio) + to_color[1] * ratio)
        b = int(from_color[2] * (1 - ratio) + to_color[2] * ratio)
        for x in range(w):
            pixels[x, y] = (r, g, b)

    return img


def wrap_text(text, font, max_width, draw):
    """Текстийг тодорхой өргөнд багтаж байхаар мөрөнд хуваах"""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines[:3]  # Максимум 3 мөр


def draw_badge(draw, text, x, y, bg_color, fg_color, font):
    """Категорийн badge зурах (жижиг толбо)"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding_x = 16
    padding_y = 10

    # Background rectangle
    draw.rectangle(
        [x, y, x + text_w + 2 * padding_x, y + text_h + 2 * padding_y],
        fill=bg_color
    )

    # Text
    draw.text(
        (x + padding_x, y + padding_y - 2),
        text,
        fill=fg_color,
        font=font
    )


# =============================================================================
# ГОЛ ЗУРАГ ҮҮСГЭХ ФУНКЦ
# =============================================================================

def generate_image(post, index):
    """Нэг постод тохирсон зураг үүсгэх"""
    category = post.get("category", DEFAULT_CATEGORY).lower()
    if category not in CATEGORY_STYLES:
        category = DEFAULT_CATEGORY

    style = CATEGORY_STYLES[category]
    headline = post["headline"]
    original_url = post.get("original_url", "")

    # 1. Background: OG зураг эсвэл gradient fallback
    og_img = None
    if original_url:
        og_img = fetch_og_image(original_url)

    if og_img:
        # OG зургийг resize + crop
        og_img = og_img.resize(
            (WIDTH, HEIGHT), Image.LANCZOS
        )
        # Хар давхарга нэмэх (текст унших боломжтой байхаар)
        enhancer = ImageEnhance.Brightness(og_img)
        bg = enhancer.enhance(BG_BRIGHTNESS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=1))
    else:
        # Gradient fallback (категорийн өнгөөр)
        bg = create_gradient(
            style["gradient_from"],
            style["gradient_to"],
            (WIDTH, HEIGHT)
        )

    draw = ImageDraw.Draw(bg)

    # 2. Category badge (зүүн дээд)
    try:
        badge_font = ImageFont.truetype(FONT_BOLD, FONT_SIZE_BADGE)
    except:
        badge_font = ImageFont.load_default()

    draw_badge(
        draw,
        style["badge_text"],
        x=40, y=40,
        bg_color=style["badge_bg"],
        fg_color=style["badge_fg"],
        font=badge_font
    )

    # 3. Headline (голлодоо)
    try:
        headline_font = ImageFont.truetype(FONT_BOLD, FONT_SIZE_HEADLINE)
    except:
        headline_font = ImageFont.load_default()

    max_width = WIDTH - 80  # 40px padding хоёр талаас
    lines = wrap_text(headline, headline_font, max_width, draw)

    # Text шугамын өндөр
    line_height = FONT_SIZE_HEADLINE + 12

    # Нийт text block өндөр
    total_text_height = len(lines) * line_height

    # Зүүн доод орхиж, дунд-доод талд байрлуул
    start_y = HEIGHT - total_text_height - 140

    for i, line in enumerate(lines):
        # Shadow (гүн)
        draw.text(
            (42, start_y + i * line_height + 2),
            line,
            fill=(0, 0, 0, 180),
            font=headline_font
        )
        # Main text
        draw.text(
            (40, start_y + i * line_height),
            line,
            fill=(255, 255, 255),
            font=headline_font
        )

    # 4. Bottom bar (logo + URL)
    bar_height = 70
    draw.rectangle(
        [0, HEIGHT - bar_height, WIDTH, HEIGHT],
        fill=(10, 10, 10)
    )

    # Orange accent line дээр
    draw.rectangle(
        [0, HEIGHT - bar_height - 3, WIDTH, HEIGHT - bar_height],
        fill=(255, 107, 26)
    )

    # Footer text
    try:
        footer_font = ImageFont.truetype(FONT_BOLD, FONT_SIZE_FOOTER)
    except:
        footer_font = ImageFont.load_default()

    draw.text(
        (40, HEIGHT - bar_height + 22),
        "🟠 Orange News",
        fill=(255, 107, 26),
        font=footer_font
    )

    draw.text(
        (WIDTH - 220, HEIGHT - bar_height + 24),
        "orangenews.mn",
        fill=(200, 200, 200),
        font=footer_font
    )

    # 5. Хадгалах
    today = datetime.now().strftime("%Y%m%d")
    filename = f"post_{index:02d}_{today}.png"
    filepath = OUTPUT_DIR / filename
    bg.save(filepath, "PNG", quality=95)

    return str(filepath)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("🎨 Orange News Image Generator v5 эхэлж байна...\n")

    if not os.path.exists(INPUT_FILE):
        print(f"❌ {INPUT_FILE} файл олдсонгүй!")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)

    print(f"📥 {len(posts)} пост боловсруулах...\n")

    generated = []
    for i, post in enumerate(posts, 1):
        print(f"[{i}/{len(posts)}] {post['headline'][:60]}...")

        try:
            filepath = generate_image(post, i)
            post["image_path"] = filepath
            generated.append(post)
            cat_emoji = CATEGORY_STYLES.get(
                post.get("category", DEFAULT_CATEGORY),
                CATEGORY_STYLES[DEFAULT_CATEGORY]
            )["badge_text"]
            print(f"  ✅ {cat_emoji} → {filepath}")
        except Exception as e:
            print(f"  ❌ Алдаа: {e}")
            continue

    # image_path-тай болсон posts-г буцаан хадгалах
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(generated, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ Амжилттай! {len(generated)}/{len(posts)} зураг үүсгэв")
    print(f"📁 Хадгалсан: {OUTPUT_DIR}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
