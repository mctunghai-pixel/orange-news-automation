"""
Orange News — Market Watch LIVE Poster
=======================================
Зөвхөн Market Watch пост-ыг нийтэлнэ: 07:48-аас өмнө ажиллавал FB-д 08:00 MNT-д
товлоно (scheduled_publish_time), хожуу ажиллавал шууд, 11:00-оос хойш бол abort.
Өдөрт нэг удаа (logs/mw_published.json).
fb_poster.py-ийн helper-уудыг re-use хийнэ (DRY).

Hybrid architecture:
  - Энэ скрипт: 07:45 MNT cron → ~08:00 MNT шууд publish (Market Watch x1)
  - fb_poster.py: 06:00 MNT cron → 09:00-17:00 MNT scheduled (News x9)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from fb_poster import (
    INPUT_FILE,
    format_post,
    get_page_token,
    get_post_image,
    log,
    post_photo_to_facebook,
    post_to_facebook,
)

MNT_OFFSET = timedelta(hours=8)
TARGET_HOUR_MNT = 8        # Зорьж буй нийтлэх цаг: 08:00 MNT
STALE_MINUTES = 180        # 11:00 MNT-ээс хойш → abort (GitHub cron 2+ цаг хоцордог)
MIN_SCHEDULE_LEAD_MIN = 12 # FB scheduled_publish_time ≥ 10 мин урьдчилсан байх ёстой
STATE_FILE = "logs/mw_published.json"


def _now_mnt():
    return datetime.now(timezone.utc) + MNT_OFFSET


def already_done_today() -> bool:
    """Once-per-day guard: several crons may fire, only the first one posts."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("date") == _now_mnt().strftime("%Y-%m-%d")
    except Exception:
        return False


def mark_done(post_id, mode, publish_at):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": _now_mnt().strftime("%Y-%m-%d"), "id": post_id,
                   "mode": mode, "publish_at_mnt": publish_at}, f, ensure_ascii=False, indent=2)


def target_publish_time():
    """Unix ts of 08:00 MNT today if it is far enough ahead to schedule, else None (publish now)."""
    now = _now_mnt()
    target = now.replace(hour=TARGET_HOUR_MNT, minute=0, second=0, microsecond=0)
    if (target - now).total_seconds() / 60 >= MIN_SCHEDULE_LEAD_MIN:
        return int((target - MNT_OFFSET).replace(tzinfo=timezone.utc).timestamp()), target.strftime("%H:%M")
    return None, now.strftime("%H:%M")


def find_market_watch(posts):
    for p in posts:
        if (p.get("category") == "market_watch"
                or p.get("use_market_watch_image")
                or p.get("type") == "market_watch"):
            return p
    return None


def is_stale() -> bool:
    """Зорилтот 08:00 MNT-ээс 30 мин илүү хоцорсон эсэхийг шалгана."""
    now_mnt = datetime.now(timezone.utc) + MNT_OFFSET
    target = now_mnt.replace(hour=TARGET_HOUR_MNT, minute=0, second=0, microsecond=0)
    delta_min = (now_mnt - target).total_seconds() / 60
    if delta_min > STALE_MINUTES:
        log(f"❌ STALE abort: зорилтот 08:00 MNT-ээс {delta_min:.1f} мин хоцорсон (>{STALE_MINUTES})")
        return True
    return False


def run(live: bool) -> int:
    mode = "LIVE" if live else "TEST"
    log("=" * 50)
    log(f"📊 Market Watch LIVE Poster | Mode: {mode}")
    log("=" * 50)

    if already_done_today():
        log("↩ Market Watch өнөөдөр аль хэдийн нийтлэгдсэн/товлогдсон — skip")
        return 0

    if is_stale():
        return 1

    if not os.path.exists(INPUT_FILE):
        log(f"❌ {INPUT_FILE} олдсонгүй")
        return 1

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)

    mw = find_market_watch(posts)
    if not mw:
        log("❌ Market Watch пост translated_posts.json-д алга")
        return 1

    text = format_post(mw)
    if not text:
        log("❌ Market Watch текст хоосон")
        return 1

    image_path = get_post_image(mw, 0)
    log(f"📝 {mw.get('headline', '')[:60]}")
    log(f"📏 Текст: {len(text)} тэмдэгт")
    if image_path:
        log(f"🖼️  Зураг: {os.path.basename(image_path)}")

    if not live:
        log(f"✓ TEST — нийтлэх байсан ({len(text)} тэмдэгт)")
        return 0

    page_id = os.environ.get("FB_PAGE_ID")
    user_token = os.environ.get("FB_ACCESS_TOKEN")
    if not page_id or not user_token:
        log("❌ FB_PAGE_ID эсвэл FB_ACCESS_TOKEN олдсонгүй")
        return 1
    access_token = get_page_token(user_token, page_id)

    sched_ts, publish_at = target_publish_time()
    try:
        if image_path and os.path.exists(image_path):
            result = post_photo_to_facebook(
                text, page_id, access_token, image_path, scheduled_time=sched_ts
            )
        else:
            result = post_to_facebook(
                text, page_id, access_token, scheduled_time=sched_ts
            )

        if "id" in result:
            mode = "scheduled" if sched_ts else "now"
            log(f"✅ {'08:00-д товлогдсон' if sched_ts else 'Шууд нийтлэгдсэн'}: {result['id']} ({publish_at} MNT)")
            mark_done(result["id"], mode, publish_at)
            return 0
        err = result.get("error", {}).get("message", str(result))
        log(f"❌ FB API: {err}")
        return 1
    except Exception as e:
        log(f"❌ Exception: {e}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Бодит LIVE нийтлэх")
    args = parser.parse_args()
    sys.exit(run(live=args.live))
