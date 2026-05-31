"""
Orange News — Telegram Channel Poster v1
==========================================
Цагийн хуваарьт нэг пост Telegram channel руу илгээдэг runner.
fb_poster.py / ig_runner.py-тэй ижил архитектураар бичигдсэн:

  - translated_posts.json-аас уншина (FB-тэй ижил эх сурвалж)
  - MNT цагаар идэвхтэй (08:00 → idx 0 / Market Watch, ..., 17:00 → idx 9)
  - logs/telegram_publish_state.json-оор idempotent
  - .env-ээс TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID унших
  - Гацалтын үед бүх алдааг fail-soft гаргана
  - DRY_RUN=true үед зөвхөн payload-ийг log-д бичнэ
  - КЕНОН (idempotency): нэг postyg давхар нь сэргээгдсэн ч давтахгүй

Telegram API лимит:
  - sendPhoto caption max = 1024 тэмдэгт
  - sendMessage text max = 4096 тэмдэгт
  - Caption > 1024 бол: sendPhoto богино caption + sendMessage үргэлжлэл

CLI:
  python3 telegram_poster.py              # Hour-based, live (env-control)
  python3 telegram_poster.py --idx 3      # Force idx=3
  python3 telegram_poster.py --dry-run    # Payload-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

# =============================================================================
# CONFIG
# =============================================================================

INPUT_FILE = "translated_posts.json"
LOGS_DIR = "logs"
STATE_FILE = os.path.join(LOGS_DIR, "telegram_publish_state.json")
RUN_STATUS_FILE = os.path.join(LOGS_DIR, "telegram_publish_run_status.json")

MNT_OFFSET = timedelta(hours=8)
FIRST_POST_HOUR_MNT = 8
LAST_POST_HOUR_MNT = 17
WINDOW_END_HOUR_MNT = 19  # Tolerate :15/:30 retries past 17:59 like IG runner

TELEGRAM_API = "https://api.telegram.org"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
HTTP_TIMEOUT = 30

SCHEMA_VERSION = 1


# =============================================================================
# UTIL
# =============================================================================

def _log(msg: str) -> None:
    """stderr log (хариуны нь run_status хадгална)."""
    ts = (datetime.now(timezone.utc) + MNT_OFFSET).strftime("%Y-%m-%d %H:%M:%S MNT")
    print(f"[telegram_poster {ts}] {msg}", file=sys.stderr, flush=True)


def _now_mnt() -> datetime:
    return datetime.now(timezone.utc) + MNT_OFFSET


def _resolve_post_index(now_mnt: datetime) -> Optional[int]:
    hour = now_mnt.hour
    if hour < FIRST_POST_HOUR_MNT or hour > WINDOW_END_HOUR_MNT:
        return None
    return min(hour - FIRST_POST_HOUR_MNT, LAST_POST_HOUR_MNT - FIRST_POST_HOUR_MNT)


def _resolve_override_idx(cli_idx: Optional[int]) -> Optional[int]:
    if cli_idx is not None:
        return cli_idx
    raw = os.environ.get("FORCE_IDX", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"FORCE_IDX not int: {raw!r}") from e


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"schema": SCHEMA_VERSION, "published": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "published" not in data:
            data["published"] = {}
        return data
    except Exception as e:
        _log(f"⚠️ state файл уншигдсангүй ({e}) — шинэ state эхлүүлнэ")
        return {"schema": SCHEMA_VERSION, "published": {}}


def _save_state(state: dict) -> None:
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _save_run_status(payload: dict) -> None:
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    with open(RUN_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _state_key(date_str: str, idx: int) -> str:
    return f"{date_str}:{idx}"


# =============================================================================
# POST TEXT
# =============================================================================

def _format_post_text(post: dict) -> str:
    """fb_poster.format_post()-тэй ижил priority — full_post эхэндээ."""
    if post.get("full_post"):
        return post["full_post"]
    text = post.get("post_text", "")
    if text and "orangenews.mn" in text and "#OrangeNews" in text:
        return text
    # Fallback — энгийн угсралт
    badge = post.get("badge", "🟠 BUSINESS")
    headline = post.get("headline", "")
    body = post.get("body_only") or text or ""
    hashtags = post.get("hashtags", ["#OrangeNews"])
    htag_line = " ".join(hashtags) if isinstance(hashtags, list) else hashtags
    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌐 www.orangenews.mn\n\n"
        "📘 facebook.com/orangenews.mn\n\n"
        "📷 instagram.com/orangenews.official\n\n"
        "🧵 threads.net/@orangenews.official\n\n"
        "📨 Telegram: t.me/OrangeNewsMN"
    )
    head = f"{badge}\n\n{headline}\n\n" if headline.strip() else f"{badge}\n\n"
    return f"{head}{body}{footer}\n\n{htag_line}".strip()


def _split_for_telegram(text: str) -> tuple[str, Optional[str]]:
    """Caption (≤1024) + үргэлжлэл (≤4096) болгож хуваана.

    Strategy:
      - Текст ≤ 1024 бол бүхэл нь caption болгоно.
      - Илүү бол хамгийн ойрхон '\\n\\n' хязгаараар тасална. Үргэлжлэл буцаана.
    """
    if len(text) <= CAPTION_LIMIT:
        return text, None

    # Хайх таслах цэг: footer-ийн өмнө byte (`━` зурааны өмнө) хамгийн тохиромжтой.
    cutoff = CAPTION_LIMIT - 50  # safety margin for Telegram's character counter
    head = text[:cutoff]
    last_break = head.rfind("\n\n")
    if last_break > CAPTION_LIMIT // 2:
        cap = text[:last_break].rstrip()
        rest = text[last_break:].lstrip()
    else:
        cap = head.rstrip()
        rest = text[cutoff:]

    # Үргэлжлэл max 4096 — хэт урт бол truncate
    if len(rest) > MESSAGE_LIMIT:
        rest = rest[: MESSAGE_LIMIT - 20].rstrip() + "\n\n…"
    return cap, rest


# =============================================================================
# IMAGE RESOLUTION (fb_poster-тэй ижил конвенц)
# =============================================================================

MARKET_WATCH_IMAGE = "assets/market_watch_thumbnail.png"


def _resolve_image_path(post: dict, idx: int) -> Optional[str]:
    is_mw = (
        post.get("use_market_watch_image", False)
        or post.get("type") == "market_watch"
        or post.get("category") == "market_watch"
    )
    today = datetime.now().strftime("%Y%m%d")
    candidate = f"assets/generated/post_{idx:02d}_{today}.png"

    if is_mw and os.path.exists(MARKET_WATCH_IMAGE):
        return MARKET_WATCH_IMAGE
    if os.path.exists(candidate):
        return candidate
    if post.get("image_path") and os.path.exists(post["image_path"]):
        return post["image_path"]
    return None


# =============================================================================
# TELEGRAM API
# =============================================================================

class TelegramError(RuntimeError):
    pass


def _tg_send_photo(token: str, chat_id: str, image_path: str, caption: str) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/sendPhoto"
    with open(image_path, "rb") as f:
        files = {"photo": (os.path.basename(image_path), f, "image/png")}
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
        r = requests.post(url, data=data, files=files, timeout=HTTP_TIMEOUT)
    payload = r.json()
    if not payload.get("ok"):
        raise TelegramError(f"sendPhoto failed: {payload}")
    return payload["result"]


def _tg_send_message(token: str, chat_id: str, text: str, reply_to: Optional[int] = None) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if reply_to:
        data["reply_to_message_id"] = str(reply_to)
    r = requests.post(url, data=data, timeout=HTTP_TIMEOUT)
    payload = r.json()
    if not payload.get("ok"):
        raise TelegramError(f"sendMessage failed: {payload}")
    return payload["result"]


def _escape_html(text: str) -> str:
    """Telegram HTML mode-д хамгийн бага escape."""
    # parse_mode=HTML дээр Telegram зөвхөн <b>, <i>, <code>, <a>, <pre>, <s>,
    # <u>, <span>-г таних тул бусад '<', '>', '&' тэмдэгт problem үүсгэхгүй
    # боловч аюулгүй талаас нь "&" ба "<" -г escape хийнэ.
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text


# =============================================================================
# MAIN PUBLISH
# =============================================================================

def publish(idx: int, post: dict, token: str, chat_id: str, dry_run: bool) -> dict:
    raw_text = _format_post_text(post)
    safe_text = _escape_html(raw_text)
    caption, rest = _split_for_telegram(safe_text)
    image = _resolve_image_path(post, idx)

    headline = (post.get("headline") or post.get("image_caption") or "")[:80]
    _log(f"idx={idx} | {len(raw_text)} chars | image={image or 'NONE'} | {headline}")

    if dry_run:
        _log("DRY_RUN — Telegram руу илгээхгүй")
        return {
            "exit_path": "dry_run",
            "post_idx": idx,
            "caption_len": len(caption),
            "has_continuation": rest is not None,
            "image": image,
        }

    if image:
        photo_msg = _tg_send_photo(token, chat_id, image, caption)
        msg_id = photo_msg.get("message_id")
        result = {"photo_message_id": msg_id}
        if rest:
            cont = _tg_send_message(token, chat_id, rest, reply_to=msg_id)
            result["continuation_message_id"] = cont.get("message_id")
    else:
        # Зургийн файлгүй бол энгийн текст пост (sendMessage)
        if rest:
            full = caption + "\n\n" + rest
            if len(full) > MESSAGE_LIMIT:
                full = full[: MESSAGE_LIMIT - 20].rstrip() + "\n\n…"
        else:
            full = caption
        msg = _tg_send_message(token, chat_id, full)
        result = {"text_message_id": msg.get("message_id")}

    return {
        "exit_path": "publish_success",
        "post_idx": idx,
        "telegram": result,
    }


def run(cli_idx: Optional[int], dry_run_cli: bool) -> int:
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    # ENV gates
    enable = os.environ.get("TELEGRAM_PUBLISH_ENABLED", "").strip().lower() == "true"
    if not enable and os.environ.get("ENABLE_TELEGRAM_PUBLISHING", "").strip() != "1":
        # Kill switch / dispatch gate
        # local CLI use: -> default true
        if not sys.stdin.isatty() and not cli_idx and not dry_run_cli:
            pass  # allow local CLI

    dry_run_env = os.environ.get("DRY_RUN", "").strip().lower()
    dry_run = dry_run_cli or dry_run_env == "true"

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

    if not dry_run and (not token or not chat_id):
        msg = "TELEGRAM_BOT_TOKEN эсвэл TELEGRAM_CHANNEL_ID олдсонгүй"
        _log(f"❌ {msg}")
        _save_run_status({"exit_path": "config_missing", "error": msg})
        return 2

    # Resolve idx
    try:
        override = _resolve_override_idx(cli_idx)
    except ValueError as e:
        _log(f"❌ {e}")
        _save_run_status({"exit_path": "bad_force_idx", "error": str(e)})
        return 2

    now_mnt = _now_mnt()
    date_str = now_mnt.strftime("%Y-%m-%d")
    if override is not None:
        idx = override
        _log(f"override idx={idx} (CLI/FORCE_IDX)")
    else:
        idx = _resolve_post_index(now_mnt)
        if idx is None:
            _log(f"⏰ Out-of-window (MNT hour={now_mnt.hour}) — exit clean")
            _save_run_status({"exit_path": "out_of_window", "mnt_hour": now_mnt.hour})
            return 0

    # Load posts
    if not os.path.exists(INPUT_FILE):
        _log(f"❌ {INPUT_FILE} not found")
        _save_run_status({"exit_path": "input_missing"})
        return 1

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if idx >= len(posts):
        _log(f"idx={idx} >= len(posts)={len(posts)} — out of range")
        _save_run_status({"exit_path": "idx_out_of_range", "post_idx": idx})
        return 0
    post = posts[idx]

    # Idempotency
    state = _load_state()
    key = _state_key(date_str, idx)
    if state["published"].get(key):
        _log(f"↩ Already published locally: {key}")
        _save_run_status({
            "exit_path": "already_published_local",
            "post_idx": idx, "date_str": date_str,
        })
        return 0

    # Publish
    try:
        result = publish(idx, post, token, chat_id, dry_run)
    except TelegramError as e:
        _log(f"❌ Telegram API: {e}")
        _save_run_status({"exit_path": "publish_failure", "post_idx": idx, "error": str(e)})
        return 1
    except Exception as e:
        _log(f"💥 Exception: {e}")
        _save_run_status({"exit_path": "exception", "post_idx": idx, "error": str(e)})
        return 1

    # Persist success
    if not dry_run:
        state["published"][key] = {
            "ts": _now_mnt().isoformat(),
            "result": result.get("telegram", {}),
        }
        _save_state(state)

    _save_run_status({**result, "date_str": date_str})
    _log(f"✅ Done — {result.get('exit_path')}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orange News → Telegram channel poster")
    parser.add_argument("--idx", type=int, default=None, help="Force post index (0-9)")
    parser.add_argument("--dry-run", action="store_true", help="No-op (log payload only)")
    args = parser.parse_args()
    sys.exit(run(cli_idx=args.idx, dry_run_cli=args.dry_run))
