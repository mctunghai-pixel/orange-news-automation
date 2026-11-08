"""
brand_card.py — Aravt News Visual Standard v2 (approved 2026-11-08)

Same layouts and function signatures as v1 (so image_generator.py is unchanged):
  * news_card        1080x1350 feed post
  * market_watch_card 1080x1350 data card
  * reel_frame       1080x1920 Reels frame
  * web_card         1200x675 website thumbnail
  * gradient_photo   branded fallback background
Palette A "Navy + Gold"; logo drawn in code (10 bars = аравт + market chart).
`logo_path` arguments are accepted for backward compatibility but ignored.
All names/links come from brand.py.
"""
from PIL import Image, ImageDraw, ImageFont, ImageOps
import os

import brand as B

W, H = 1080, 1350
PHOTO_H = 820
PAD = 64
INK = B.NAVY            # panel background
ACCENT = B.GOLD
WHITE = (255, 255, 255)
GREY = B.GREY

FONT_DIR = os.environ.get("ON_FONT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts"))
F_HEAD = os.path.join(FONT_DIR, "Inter-ExtraBold.otf")
F_BLACK = os.path.join(FONT_DIR, "Inter-Black.otf")
F_BOLD = os.path.join(FONT_DIR, "Inter-Bold.otf")
F_REG = os.path.join(FONT_DIR, "Inter-Medium.otf")

# v2: one accent (gold) for every category — the label text carries the meaning
CATEGORY_LABEL = {k: (v, ACCENT) for k, v in {
    "finance": "САНХҮҮ", "economy": "ЭДИЙН ЗАСАГ", "stock": "ХӨРӨНГИЙН ЗАХ",
    "tech": "ТЕХНОЛОГИ", "ai": "ХИЙМЭЛ ОЮУН", "crypto": "КРИПТО",
    "energy": "ЭРЧИМ ХҮЧ", "commodity": "ТҮҮХИЙ ЭД", "mongolia": "МОНГОЛ",
    "video": "ВИДЕО МЭДЭЭ",
}.items()}


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


# ---------------------------------------------------------------- logo
def logo_mark(size, bg=True):
    """Square mark: 10 bars in a market-chart rhythm (аравт = 10), last bar gold.
    Below 48px it simplifies to 5 bars so it stays readable as a favicon."""
    S = size * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if bg:
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.2), fill=INK + (255,),
                            outline=ACCENT + (255,), width=max(4, S // 40))
    heights = [0.34, 0.52, 0.42, 0.64, 0.50, 0.72, 0.60, 0.80, 0.70, 1.0] if size >= 48 \
        else [0.42, 0.66, 0.52, 0.78, 1.0]
    n, m = len(heights), S * 0.2
    gap = S * (0.026 if n == 10 else 0.06)
    bw = (S - 2 * m - (n - 1) * gap) / n
    base = S - m
    for i, hh in enumerate(heights):
        h = (S - 2 * m) * hh
        x0 = m + i * (bw + gap)
        d.rectangle((x0, base - h, x0 + bw, base), fill=(ACCENT if i == n - 1 else WHITE) + (255,))
    return im.resize((size, size), Image.LANCZOS)


def logo_lockup(height):
    """Mark + 'ARAVT' / 'N E W S' wordmark on transparent background."""
    mark = logo_mark(height)
    f1 = font(F_BLACK, int(height * 0.52))
    f2 = font(F_BOLD, int(height * 0.26))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w1, w2 = tmp.textlength("ARAVT", font=f1), tmp.textlength("N E W S", font=f2)
    gap = int(height * 0.22)
    im = Image.new("RGBA", (height + gap + int(max(w1, w2)) + 4, height), (0, 0, 0, 0))
    im.paste(mark, (0, 0), mark)
    d = ImageDraw.Draw(im)
    x = height + gap
    d.text((x, int(height * -0.04)), "ARAVT", font=f1, fill=WHITE)
    # "NEWS" justified to the full width of "ARAVT" (approved lockup C, 2026-11-08)
    ws = [d.textlength(c, font=f2) for c in "NEWS"]
    x0, x1 = x + height * 0.02, x + w1 - height * 0.02
    step = (x1 - x0 - sum(ws)) / 3
    cx = x0
    for c, cw in zip("NEWS", ws):
        d.text((cx, int(height * 0.64)), c, font=f2, fill=ACCENT)
        cx += cw + step
    return im


def _paste_lockup_chip(card, height, x, y, pad_x=18, pad_y=14):
    lock = logo_lockup(height)
    chip = Image.new("RGBA", (lock.width + 2 * pad_x, lock.height + 2 * pad_y), INK + (220,))
    card.paste(chip, (x - pad_x, y - pad_y), chip)
    card.paste(lock, (x, y), lock)


def _fade(card, top, height, w, power=1.6):
    fade = Image.new("L", (1, height))
    for y in range(height):
        fade.putpixel((0, y), int(255 * (y / (height - 1)) ** power))
    card.paste(Image.new("RGB", (w, height), INK), (0, top), fade.resize((w, height)))


def _footer(d, w, h, size=30, y_off=66):
    d.rectangle((0, h - y_off - 26, w, h - y_off - 20), fill=ACCENT)
    ff = font(F_BOLD, size)
    d.text((PAD, h - y_off), B.DOMAIN, font=ff, fill=WHITE)
    d.text((w - PAD - d.textlength(B.HANDLE, font=ff), h - y_off), B.HANDLE, font=ff, fill=ACCENT)


def _label(d, x, y, label, size=28, bar_h=50, bar_w=8):
    d.rectangle((x, y, x + bar_w, y + bar_h), fill=ACCENT)
    d.text((x + bar_w + 14, y + (bar_h - size) // 2 - 2), label, font=font(F_BOLD, size), fill=ACCENT)


# ---------------------------------------------------------------- cards
def news_card(photo_path, headline, category, source, date_str, logo_path, out_path,
              photo_credit="Pixabay"):
    label, _ = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ACCENT))
    card = Image.new("RGB", (W, H), INK)
    card.paste(cover_crop(Image.open(photo_path), W, PHOTO_H), (0, 0))
    _fade(card, PHOTO_H - 260, 260, W)
    d = ImageDraw.Draw(card)

    _paste_lockup_chip(card, 66, PAD, PAD)

    if photo_credit and str(photo_credit).lower() != "none":   # no chip on branded gradients
        fc = font(F_REG, 20)
        credit = f"Зураг: {photo_credit}"
        cw = d.textlength(credit, font=fc)
        d.rounded_rectangle((W - PAD - cw - 20, PAD + 18, W - PAD + 6, PAD + 52), radius=6, fill=(0, 0, 0))
        d.text((W - PAD - cw - 7, PAD + 23), credit, font=fc, fill=(230, 230, 230))

    fh, lines = fit_headline(d, headline, W - 2 * PAD)
    block_h = 50 + 28 + len(lines) * int(fh.size * 1.18) + 18 + 34
    y = max(PHOTO_H - 140, H - 140 - block_h)
    _label(d, PAD, y, label)
    y += 78
    for ln in lines:
        d.text((PAD, y), ln, font=fh, fill=WHITE)
        y += int(fh.size * 1.18)
    d.text((PAD, y + 18), f"Эх сурвалж: {source}   ·   {date_str}", font=font(F_REG, 28), fill=GREY)
    _footer(d, W, H)
    card.save(out_path, quality=92)
    return out_path


def market_watch_card(rows, date_str, logo_path, out_path):
    """rows: list of (section, [(name, value, change_pct)])"""
    card = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(card)
    lock = logo_lockup(66)
    card.paste(lock, (PAD, PAD), lock)
    d.text((PAD, PAD + 110), "MARKET WATCH", font=font(F_HEAD, 76), fill=WHITE)
    d.text((PAD, PAD + 202), f"Өглөөний зах зээлийн тойм  ·  {date_str}", font=font(F_REG, 30), fill=GREY)
    d.rectangle((PAD, PAD + 258, PAD + 120, PAD + 264), fill=ACCENT)
    y = PAD + 304
    fs, fn, fv = font(F_BOLD, 26), font(F_REG, 34), font(F_BOLD, 34)
    for section, items in rows:
        d.text((PAD, y), section, font=fs, fill=ACCENT)
        y += 46
        for name, value, chg in items:
            d.text((PAD, y), name, font=fn, fill=WHITE)
            vw = d.textlength(value, font=fv)
            d.text((W - PAD - 190 - vw, y), value, font=fv, fill=WHITE)
            if chg is not None:
                col = (40, 200, 120) if chg >= 0 else (240, 80, 80)
                txt = f"{'▲' if chg >= 0 else '▼'} {abs(chg):.2f}%"
                d.text((W - PAD - d.textlength(txt, font=fv), y), txt, font=fv, fill=col)
            y += 52
        y += 22
    _footer(d, W, H)
    card.save(out_path, quality=92)
    return out_path


def reel_frame(photo_path, headline, category, subtitle, idx, total, logo_path, out_path):
    """1080x1920 Reels frame: full photo, headline, burned-in Mongolian subtitle."""
    RW, RH = 1080, 1920
    label, _ = CATEGORY_LABEL.get(category, ("МЭДЭЭ", ACCENT))
    card = Image.new("RGB", (RW, RH), INK)
    card.paste(cover_crop(Image.open(photo_path), RW, 1150), (0, 0))
    _fade(card, 1150 - 420, 420, RW, power=1.4)
    d = ImageDraw.Draw(card)
    seg = (RW - 2 * PAD) // max(1, total)
    for i in range(total):
        x0 = PAD + i * seg
        d.rectangle((x0, 70, x0 + seg - 10, 78), fill=ACCENT if i <= idx else (80, 86, 100))
    _paste_lockup_chip(card, 76, PAD, 120, pad_x=20, pad_y=16)
    y = 900
    _label(d, PAD, y, label, size=34, bar_h=60, bar_w=10)
    fh, lines = fit_headline(d, headline, RW - 2 * PAD, max_lines=4, sizes=(80, 74, 68, 62))
    y += 96
    for ln in lines:
        d.text((PAD, y), ln, font=fh, fill=WHITE)
        y += int(fh.size * 1.16)
    fs = font(F_BOLD, 44)
    sl = wrap(d, subtitle, fs, RW - 2 * PAD - 60)[:3]
    bh = len(sl) * 60 + 50
    by = max(y + 50, RH - 300 - bh)
    d.rounded_rectangle((PAD, by, RW - PAD, by + bh), radius=18, fill=(0, 0, 0))
    yy = by + 25
    for ln in sl:
        d.text(((RW - d.textlength(ln, font=fs)) / 2, yy), ln, font=fs, fill=(255, 224, 120))
        yy += 60
    _footer(d, RW, RH, size=34, y_off=170)
    card.save(out_path, quality=92)
    return out_path


def web_card(photo_path, category, logo_path, out_path):
    """1200x675 (16:9) website thumbnail: photo + logo chip.
    The site renders headline and category itself, so no text here."""
    WW, WH = 1200, 675
    card = cover_crop(Image.open(photo_path), WW, WH)
    _paste_lockup_chip(card, 44, 42, 37, pad_x=14, pad_y=11)
    card.convert("RGB").save(out_path, quality=88)
    return out_path


def gradient_photo(category, out_path, size=(1440, 960)):
    """Branded fallback background when no licensed photo is available."""
    w, h = size
    img = Image.new("RGB", size, INK)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        c = tuple(int(ACCENT[i] * (0.30 - 0.25 * t) + INK[i] * (0.70 + 0.25 * t)) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    for x in range(-h, w, 90):          # subtle diagonal texture
        d.line([(x, h), (x + h, 0)], fill=tuple(min(255, v + 10) for v in INK), width=2)
    img.save(out_path, quality=90)
    return out_path


def export_logo_assets(out_dir="assets"):
    """Regenerate logo.png (1024 mark) + logo_lockup.png + favicon sizes."""
    os.makedirs(out_dir, exist_ok=True)
    logo_mark(1024).save(os.path.join(out_dir, "logo.png"))
    lk = logo_lockup(240)
    bg = Image.new("RGBA", (lk.width + 120, lk.height + 120), INK + (255,))
    bg.paste(lk, (60, 60), lk)
    bg.save(os.path.join(out_dir, "logo_lockup.png"))
    for s in (32, 180, 512):
        logo_mark(s).save(os.path.join(out_dir, f"icon_{s}.png"))


if __name__ == "__main__":
    export_logo_assets()
