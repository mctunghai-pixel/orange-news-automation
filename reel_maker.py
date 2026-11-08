"""
reel_maker.py — Aravt News 9:16 news Reels (text + original music, no voice).

One Reel per story, ~14 s:
  0–4 s   hook: photo + category + headline + 1st key sentence
  4–8 s   key sentence 2
  8–12 s  key sentence 3
  12–14.5 end card: logo + "FOLLOW · Aravt News" + arrow to the Follow button
Slow zoom on every frame, slide transitions, and a short original music bed
synthesised here (no third-party audio → no copyright claims).

Market Watch: the day's Market Watch card on a 9:16 canvas with its own hook.

CLI test:  python3 reel_maker.py --idx 2 --out /tmp/reel.mp4
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw

import brand as BRAND
from brand_card import cover_crop, fit_headline, font, logo_lockup, wrap, F_BOLD, F_HEAD, F_BLACK, F_REG

NAVY, GOLD, WHITE, GREY = BRAND.NAVY, BRAND.GOLD, (255, 255, 255), BRAND.GREY
RW, RH, PAD = 1080, 1920, 70
FPS = 30
CATEGORY = {
    "finance": "САНХҮҮ", "economy": "ЭДИЙН ЗАСАГ", "stock": "ХӨРӨНГИЙН ЗАХ", "tech": "ТЕХНОЛОГИ",
    "ai": "ХИЙМЭЛ ОЮУН", "crypto": "КРИПТО", "energy": "ЭРЧИМ ХҮЧ", "commodity": "ТҮҮХИЙ ЭД",
    "mongolia": "МОНГОЛ", "business": "БИЗНЕС",
}


# ------------------------------------------------------------------ text
def key_sentences(post, n=3, max_chars=175):
    text = post.get("body_only") or post.get("post_text") or ""
    text = re.sub(r"[#*_`]+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    head = (post.get("headline") or "").strip()
    lines = [l for l in lines if l != head and not re.match(r"^[\W_]*[A-Z ]{3,}$", l)]
    sents = re.split(r"(?<=[.!?])\s+", " ".join(lines))
    out = []
    for s in sents:
        s = s.strip()
        if len(s) < 25 or "Эх сурвалж" in s or "━" in s:
            continue
        if len(s) > max_chars:
            s = s[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        out.append(s)
        if len(out) == n:
            break
    return out or [head]


# ------------------------------------------------------------------ frames
def _lockup_chip(card, h, x, y):
    lock = logo_lockup(h)
    chip = Image.new("RGBA", (lock.width + 40, lock.height + 30), NAVY + (225,))
    card.paste(chip, (x - 20, y - 15), chip)
    card.paste(lock, (x, y), lock)


def news_frame(photo, headline, category, line, step, total, out):
    card = Image.new("RGB", (RW, RH), NAVY)
    card.paste(cover_crop(Image.open(photo), RW, 1080), (0, 0))
    fade = Image.new("L", (1, 460))
    for y in range(460):
        fade.putpixel((0, y), int(255 * (y / 459) ** 1.3))
    card.paste(Image.new("RGB", (RW, 460), NAVY), (0, 1080 - 460), fade.resize((RW, 460)))
    d = ImageDraw.Draw(card)
    seg = (RW - 2 * PAD) // total
    for i in range(total):
        x0 = PAD + i * seg
        d.rectangle((x0, 60, x0 + seg - 12, 68), fill=GOLD if i <= step else (70, 80, 100))
    _lockup_chip(card, 70, PAD, 110)
    y = 860
    label = CATEGORY.get(category, "МЭДЭЭ")
    d.rectangle((PAD, y, PAD + 10, y + 56), fill=GOLD)
    d.text((PAD + 28, y + 8), label, font=font(F_BOLD, 34), fill=GOLD)
    y += 88
    fh, lines = fit_headline(d, headline, RW - 2 * PAD, max_lines=4, sizes=(74, 68, 62, 58, 54))
    for ln in lines:
        d.text((PAD, y), ln, font=fh, fill=WHITE)
        y += int(fh.size * 1.15)
    for size in (46, 42, 39, 36):          # shrink so the whole sentence fits in 4 lines
        fs = font(F_BOLD, size)
        sl = wrap(d, line, fs, RW - 2 * PAD - 70)
        if len(sl) <= 5:
            break
    sl = sl[:5]
    lh = int(fs.size * 1.38)
    bh = len(sl) * lh + 56
    by = max(y + 50, RH - 330 - bh)
    d.rounded_rectangle((PAD, by, RW - PAD, by + bh), radius=22, fill=(255, 255, 255))
    d.rectangle((PAD, by, PAD + 12, by + bh), fill=GOLD)
    yy = by + 28
    for ln in sl:
        d.text((PAD + 40, yy), ln, font=fs, fill=NAVY)
        yy += lh
    _footer(d)
    card.save(out)


def market_frame(mw_card, out):
    card = Image.new("RGB", (RW, RH), NAVY)
    d = ImageDraw.Draw(card)
    ft = font(F_BLACK, 66)
    y = 150
    for ln in ("Өнөөдрийн зах зээл", "нэг харцаар"):
        d.text(((RW - d.textlength(ln, font=ft)) / 2, y), ln, font=ft, fill=WHITE if y == 150 else GOLD)
        y += 84
    mw = Image.open(mw_card).convert("RGB").resize((972, 1215))
    card.paste(mw, (54, 380))
    _footer(d)
    card.save(out)


def end_frame(out, hook="Өдөр бүр дэлхийн санхүүгийн мэдээг Монгол хэлээр"):
    card = Image.new("RGB", (RW, RH), NAVY)
    d = ImageDraw.Draw(card)
    hs = [0.18, 0.28, 0.22, 0.36, 0.30, 0.44, 0.38, 0.52, 0.46, 0.62]
    for i, h in enumerate(hs):
        x = 60 + i * 98
        d.rectangle((x, RH - 260 - int(900 * h), x + 70, RH - 260), fill=(16, 32, 60) if i < 9 else (60, 55, 30))
    lock = logo_lockup(170)
    card.paste(lock, ((RW - lock.width) // 2, 520), lock)
    fh = font(F_HEAD, 56)
    y = 820
    for ln in wrap(d, hook, fh, RW - 2 * PAD):
        d.text(((RW - d.textlength(ln, font=fh)) / 2, y), ln, font=fh, fill=WHITE)
        y += 70
    y += 50
    d.rounded_rectangle((110, y, RW - 110, y + 120), radius=60, fill=GOLD)
    cta = "FOLLOW · Aravt News"
    fc = font(F_BLACK, 56)
    d.text(((RW - d.textlength(cta, font=fc)) / 2, y + 28), cta, font=fc, fill=NAVY)
    y += 170
    fa = font(F_BOLD, 40)
    t = "Доорх Follow товчийг дар"
    d.text(((RW - d.textlength(t, font=fa)) / 2, y), t, font=fa, fill=GOLD)
    d.polygon([(RW / 2 - 34, y + 70), (RW / 2 + 34, y + 70), (RW / 2, y + 120)], fill=GOLD)
    _footer(d)
    card.save(out)


def _footer(d):
    d.rectangle((0, RH - 200, RW, RH - 194), fill=GOLD)
    f = font(F_BOLD, 36)
    d.text((PAD, RH - 165), "www." + BRAND.DOMAIN, font=f, fill=WHITE)
    d.text((RW - PAD - d.textlength(BRAND.HANDLE, font=f), RH - 165), BRAND.HANDLE, font=f, fill=GOLD)


# ------------------------------------------------------------------ music
PROGRESSIONS = [
    [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]],   # Am F C G
    [[50, 53, 57], [46, 50, 53], [53, 57, 60], [48, 52, 55]],   # Dm Bb F C
    [[52, 55, 59], [48, 52, 55], [55, 59, 62], [50, 54, 57]],   # Em C G D
    [[45, 48, 52], [53, 57, 60], [48, 52, 55], [52, 56, 59]],   # Am F C E
]


def music(path, seconds, seed=0):
    sr = 44100
    rng = np.random.default_rng(seed)
    prog = PROGRESSIONS[seed % len(PROGRESSIONS)]
    bpm = 92 + (seed % 4) * 6
    beat = 60 / bpm
    n = int(sr * seconds)
    out = np.zeros(n)
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    bar = beat * 4
    k = 0
    while k * bar < seconds:
        s, e = int(k * bar * sr), min(n, int((k + 1) * bar * sr))
        tt = np.arange(e - s) / sr
        env = np.minimum(1, tt / 0.4) * np.exp(-tt * 0.35)
        for m in prog[k % 4]:
            f = hz(m)
            out[s:e] += 0.08 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
        for b in range(4):
            bs = s + int(b * beat * sr)
            be = min(e, bs + int(beat * sr * 0.9))
            if bs >= e:
                break
            tb = np.arange(be - bs) / sr
            out[bs:be] += 0.12 * np.exp(-tb * 3) * np.sin(2 * np.pi * hz(prog[k % 4][0] - 12) * tb)
        k += 1
    b = 0
    while b * beat < seconds:
        s = int(b * beat * sr)
        L = min(n - s, int(0.25 * sr))
        tk = np.arange(L) / sr
        out[s:s + L] += 0.35 * np.exp(-tk * 18) * np.sin(2 * np.pi * (55 + 90 * np.exp(-tk * 30)) * tk)
        h = int(s + beat * sr / 2)
        if h < n:
            L = min(n - h, int(0.05 * sr))
            out[h:h + L] += 0.05 * rng.standard_normal(L) * np.exp(-np.arange(L) / sr * 80)
        b += 1
    fi, fo = int(0.6 * sr), int(1.2 * sr)
    out[:fi] *= np.linspace(0, 1, fi)
    out[-fo:] *= np.linspace(1, 0, fo)
    out /= (np.max(np.abs(out)) or 1) * 1.15
    pcm = (np.stack([out, out], 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ video
def render(frames, durations, out, seed=0, xfade=0.45):
    tmp = tempfile.mkdtemp()
    total = sum(durations) - xfade * (len(frames) - 1)
    wav = os.path.join(tmp, "bg.wav")
    music(wav, total + 0.2, seed)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f, du in zip(frames, durations):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(du), "-i", f]
    cmd += ["-i", wav]
    fl = []
    for i, du in enumerate(durations):   # slow zoom-in per frame
        nfr = int(du * FPS)
        fl.append(f"[{i}:v]scale=1188:2112,zoompan=z='min(1+0.0009*on,1.05)':d={nfr}"
                  f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={RW}x{RH}:fps={FPS},setsar=1[z{i}]")
    prev, off = "[z0]", 0.0
    for i in range(1, len(frames)):
        off += durations[i - 1] - xfade
        fl.append(f"{prev}[z{i}]xfade=transition=slideleft:duration={xfade}:offset={off:.2f}[v{i}]")
        prev = f"[v{i}]"
    fl.append(f"{prev}format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(fl), "-map", "[vout]", "-map", f"{len(frames)}:a",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    return out


def make_news_reel(post, photo, out, seed=0):
    tmp = tempfile.mkdtemp()
    head = re.sub(r"\s+", " ", re.sub(r"[#*_`]+", "", post.get("headline") or "")).strip()
    lines = key_sentences(post)
    frames = []
    for i, ln in enumerate(lines):
        f = os.path.join(tmp, f"n{i}.png")
        news_frame(photo, head, (post.get("category") or "finance").lower(), ln, i, len(lines), f)
        frames.append(f)
    e = os.path.join(tmp, "end.png")
    end_frame(e)
    frames.append(e)
    durs = [4.2] * len(lines) + [2.8]
    return render(frames, durs, out, seed)


def make_market_reel(mw_card, out, seed=0):
    tmp = tempfile.mkdtemp()
    a, e = os.path.join(tmp, "mw.png"), os.path.join(tmp, "end.png")
    market_frame(mw_card, a)
    end_frame(e, "Market Watch — өглөө бүр 08:00-д")
    return render([a, e], [9.0, 3.0], out, seed)


def caption(post):
    head = re.sub(r"[#*_`]+", "", post.get("headline") or "").strip()
    lines = key_sentences(post, n=2, max_chars=220)
    raw = post.get("hashtags") or []
    raw = raw.split() if isinstance(raw, str) else list(raw)
    extra = [t if str(t).startswith("#") else f"#{t}" for t in raw if t and BRAND.HASHTAG.lower() != f"#{str(t).lstrip('#')}".lower()]
    tags = " ".join([BRAND.HASHTAG] + extra[:3])
    body = "\n\n".join([f"📰 {head}"] + lines)
    return (f"{body}\n\n👉 FOLLOW дараад өдөр бүр дэлхийн санхүүгийн мэдээг Монголоор аваарай\n"
            f"🌐 {BRAND.SITE_URL}\n📨 Telegram: {BRAND.TELEGRAM}\n\n{tags}").strip()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, default=1)
    ap.add_argument("--photo", default="")
    ap.add_argument("--out", default="/tmp/reel.mp4")
    a = ap.parse_args()
    posts = json.load(open("translated_posts.json", encoding="utf-8"))
    p = posts[a.idx]
    photo = a.photo
    if not photo:
        from brand_card import gradient_photo
        photo = gradient_photo((p.get("category") or "finance").lower(), "/tmp/_bg.jpg")
    make_news_reel(p, photo, a.out, seed=a.idx)
    print(caption(p))
    print("→", a.out)
