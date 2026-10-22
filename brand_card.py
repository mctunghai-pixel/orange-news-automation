"""
brand_card.py — Orange News visual standard v1

One template for every news post:
  * 1080x1350 (4:5) — Facebook / Instagram feed (max mobile screen space)
  * news-related photo on top (licensed free stock: Pexels), brand panel below
  * fixed logo position, category label, auto-fit headline, source + date line
  * no emoji in images (they render as empty boxes), Inter font bundled (OFL)
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import os

W, H = 1080, 1350
PHOTO_H = 820                      # photo area height
PAD = 64
ORANGE = (255, 107, 26)            # #FF6B1A brand
INK = (11, 11, 14)                 # panel background
WHITE = (255, 255, 255)
GREY = (170, 170, 178)

FONT_DIR = os.environ.get("ON_FONT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts"))
F_HEAD = os.path.join(FONT_DIR, "Inter-ExtraBold.otf")
F_BOLD = os.path.join(FONT_DIR, "Inter-Bold.otf")
F_REG = os.path.join(FONT_DIR, "Inter-Medium.otf")

CATEGORY_LABEL = {   # Mongolian labels, one accent colour per category
    "finance":  ("САНХҮҮ",     ORANGE),
    "economy":  ("ЭДИЙН ЗАСАГ", ORANGE),
    "stock":    ("ХӨРӨНГИЙН ЗАХ", ORANGE),
    "tech":     ("ТЕХНОЛОГИ",  (64, 156, 255)),
    "ai":       ("ХИЙМЭЛ ОЮУН", (170, 110, 255)),
    "crypto":   ("КРИПТО",     (247, 190, 30)),
    "energy":   ("ЭРЧИМ ХҮЧ",  (255, 140, 40)),
    "mongolia": ("МОНГОЛ",     (0, 170, 120)),
    "video":    ("ВИДЕО МЭДЭЭ", (235, 60, 60)),
}


def font(path, size):
    return ImageFont.truetype(path, size)


def cover_crop(img, w, h):
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.45))


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_headline(draw, text, max_w, max_lines=4, sizes=(72, 66, 60, 56, 52, 48)):
    for s in sizes:
        f = font(F_HEAD, s)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = font(F_HEAD, sizes[-1])
    lines = wrap(draw, text, f, max_w)[:max_lines]
    lines[-1] = lines[-1].rstrip(" .,") + "…"
    return f, lines


def logo_mark(logo_path, height):
    """Crop the 'ON' mark from the square brand logo."""
    lg = Image.open(logo_path).convert("RGB")
    w, h = lg.size
    mark = lg.crop((int(w * 0.21), int(h * 0.34), int(w * 0.79), int(h * 0.67)))
    ratio = height / mark.height
    return mark.resize((int(mark.width * ratio), height), Image.LANCZOS)


def news_card(photo_path, headline, category, source, date_str, logo_path, out_path,
              photo_credit="Pixabay"):
    label, accent = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ORANGE))
    card = Image.new("RGB", (W, H), INK)

    # 1. photo + fade into panel
    photo = cover_crop(Image.open(photo_path), W, PHOTO_H)
    card.paste(photo, (0, 0))
    fade = Image.new("L", (1, 260))
    for y in range(260):
        fade.putpixel((0, y), int(255 * (y / 259) ** 1.6))
    fade = fade.resize((W, 260))
    card.paste(Image.new("RGB", (W, 260), INK), (0, PHOTO_H - 260), fade)

    d = ImageDraw.Draw(card)

    # 2. logo — fixed top-left on dark chip
    mark = logo_mark(logo_path, 54)
    chip_w, chip_h = mark.width + 36, 54 + 28
    chip = Image.new("RGBA", (chip_w, chip_h), (11, 11, 14, 215))
    card.paste(chip, (PAD - 18, PAD - 14), chip)
    card.paste(mark, (PAD, PAD))

    # 3. photo credit (licence courtesy)
    if photo_credit:
        fc = font(F_REG, 20)
        credit = f"Зураг: {photo_credit}"
        cw = d.textlength(credit, font=fc)
        d.text((W - PAD - cw, PAD + 30), credit, font=fc, fill=(235, 235, 235))

    # 4. category label — text block anchored to bottom so short headlines don't leave a gap
    fl = font(F_BOLD, 28)
    fh, lines = fit_headline(d, headline, W - 2 * PAD)
    block_h = 50 + 28 + len(lines) * int(fh.size * 1.18) + 18 + 34
    y = max(PHOTO_H - 140, H - 140 - block_h)
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle((PAD, y, PAD + lw + 36, y + 50), radius=6, fill=accent)
    d.text((PAD + 18, y + 8), label, font=fl, fill=WHITE)

    # 5. headline (auto-fit, max 4 lines)
    y += 78
    lh = int(fh.size * 1.18)
    for ln in lines:
        d.text((PAD, y), ln, font=fh, fill=WHITE)
        y += lh

    # 6. source + date
    fm = font(F_REG, 28)
    d.text((PAD, y + 18), f"Эх сурвалж: {source}   ·   {date_str}", font=fm, fill=GREY)

    # 7. footer bar
    d.rectangle((0, H - 92, W, H - 86), fill=ORANGE)
    ff = font(F_BOLD, 30)
    d.text((PAD, H - 66), "orangenews.mn", font=ff, fill=WHITE)
    tag = "ORANGE NEWS"
    d.text((W - PAD - d.textlength(tag, font=ff), H - 66), tag, font=ff, fill=ORANGE)

    card.save(out_path, quality=92)
    return out_path


def market_watch_card(rows, date_str, logo_path, out_path):
    """rows: list of (section, [(name, value, change_pct)])"""
    card = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(card)
    mark = logo_mark(logo_path, 54)
    card.paste(mark, (PAD, PAD))
    d.text((PAD, PAD + 90), "MARKET WATCH", font=font(F_HEAD, 76), fill=WHITE)
    d.text((PAD, PAD + 182), f"Өглөөний зах зээлийн тойм  ·  {date_str}", font=font(F_REG, 30), fill=GREY)
    d.rectangle((PAD, PAD + 240, PAD + 120, PAD + 246), fill=ORANGE)
    y = PAD + 290
    fs, fn, fv = font(F_BOLD, 26), font(F_REG, 34), font(F_BOLD, 34)
    for section, items in rows:
        d.text((PAD, y), section, font=fs, fill=ORANGE)
        y += 46
        for name, value, chg in items:
            d.text((PAD, y), name, font=fn, fill=WHITE)
            vw = d.textlength(value, font=fv)
            d.text((W - PAD - 190 - vw, y), value, font=fv, fill=WHITE)
            if chg is not None:
                col = (40, 200, 120) if chg >= 0 else (240, 80, 80)
                arrow = "▲" if chg >= 0 else "▼"
                txt = f"{arrow} {abs(chg):.2f}%"
                d.text((W - PAD - d.textlength(txt, font=fv), y), txt, font=fv, fill=col)
            y += 52
        y += 22
    d.rectangle((0, H - 92, W, H - 86), fill=ORANGE)
    ff = font(F_BOLD, 30)
    d.text((PAD, H - 66), "orangenews.mn", font=ff, fill=WHITE)
    tag = "ORANGE NEWS"
    d.text((W - PAD - d.textlength(tag, font=ff), H - 66), tag, font=ff, fill=ORANGE)
    card.save(out_path, quality=92)
    return out_path


def reel_frame(photo_path, headline, category, subtitle, idx, total, logo_path, out_path):
    """1080x1920 Reels frame: full photo, headline, burned-in Mongolian subtitle."""
    RW, RH = 1080, 1920
    label, accent = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ORANGE))
    card = Image.new("RGB", (RW, RH), INK)
    card.paste(cover_crop(Image.open(photo_path), RW, 1150), (0, 0))
    fade = Image.new("L", (1, 420))
    for y in range(420):
        fade.putpixel((0, y), int(255 * (y / 419) ** 1.4))
    card.paste(Image.new("RGB", (RW, 420), INK), (0, 1150 - 420), fade.resize((RW, 420)))
    d = ImageDraw.Draw(card)
    mark = logo_mark(logo_path, 64)
    chip = Image.new("RGBA", (mark.width + 40, 64 + 32), (11, 11, 14, 215))
    card.paste(chip, (PAD - 20, 120 - 16), chip)
    card.paste(mark, (PAD, 120))
    # progress dots (story n/total)
    for i in range(total):
        x0 = PAD + i * ((RW - 2 * PAD) // total)
        d.rectangle((x0, 70, x0 + (RW - 2 * PAD) // total - 10, 78), fill=ORANGE if i <= idx else (80, 80, 86))
    fl = font(F_BOLD, 34)
    y = 900
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle((PAD, y, PAD + lw + 40, y + 60), radius=8, fill=accent)
    d.text((PAD + 20, y + 10), label, font=fl, fill=WHITE)
    fh, lines = fit_headline(d, headline, RW - 2 * PAD, max_lines=4, sizes=(80, 74, 68, 62))
    y += 96
    for ln in lines:
        d.text((PAD, y), ln, font=fh, fill=WHITE)
        y += int(fh.size * 1.16)
    # burned-in subtitle box (what the voice is saying)
    fs = font(F_BOLD, 44)
    sl = wrap(d, subtitle, fs, RW - 2 * PAD - 60)[:3]
    bh = len(sl) * 60 + 50
    by = max(y + 50, RH - 300 - bh)
    d.rounded_rectangle((PAD, by, RW - PAD, by + bh), radius=18, fill=(0, 0, 0))
    yy = by + 25
    for ln in sl:
        d.text(((RW - d.textlength(ln, font=fs)) / 2, yy), ln, font=fs, fill=(255, 214, 102))
        yy += 60
    ff = font(F_BOLD, 34)
    d.text((PAD, RH - 170), "orangenews.mn", font=ff, fill=WHITE)
    t = "@OrangeNews"
    d.text((RW - PAD - d.textlength(t, font=ff), RH - 170), t, font=ff, fill=ORANGE)
    card.save(out_path, quality=92)
    return out_path


def web_card(photo_path, category, logo_path, out_path):
    """1200x675 (16:9) website thumbnail: photo + logo chip + category label.
    The site renders the headline itself, so no text here."""
    WW, WH = 1200, 675
    label, accent = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ORANGE))
    card = cover_crop(Image.open(photo_path), WW, WH)
    d = ImageDraw.Draw(card)
    mark = logo_mark(logo_path, 44)
    chip = Image.new("RGBA", (mark.width + 28, 44 + 22), (11, 11, 14, 215))
    card.paste(chip, (28, 26), chip)
    card.paste(mark, (42, 37))
    fl = font(F_BOLD, 24)
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle((28, WH - 74, 28 + lw + 30, WH - 30), radius=6, fill=accent)
    d.text((43, WH - 68), label, font=fl, fill=WHITE)
    card.convert("RGB").save(out_path, quality=88)
    return out_path


def gradient_photo(category, out_path, size=(1440, 960)):
    """Branded fallback background when no licensed photo is available."""
    _, accent = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ORANGE))
    w, h = size
    img = Image.new("RGB", size, INK)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        c = tuple(int(accent[i] * (0.55 - 0.45 * t) + INK[i] * (0.45 + 0.45 * t)) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    for x in range(-h, w, 90):          # subtle diagonal texture
        d.line([(x, h), (x + h, 0)], fill=tuple(min(255, v + 10) for v in INK), width=2)
    img.save(out_path, quality=90)
    return out_path
