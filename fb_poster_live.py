"""
Orange News — Market Watch LIVE Poster
=======================================
Зөвхөн Market Watch пост-ыг шууд LIVE нийтэлнэ (scheduled_publish_time ашиглахгүй).
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
STALE_MINUTES = 30         # 30+ мин хоцрол → abort (stale data protection)


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
        log(f"❌ STALE abort: зорилтот 08:00 MNT-ээс {delta_min:.1f} мин хоцорсон (>30)")
        return True
    return False


def run(live: bool) -> int:
    mode = "LIVE" if live else "TEST"
    log("=" * 50)
    log(f"📊 Market Watch LIVE Poster | Mode: {mode}")
    log("=" * 50)

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

    try:
        if image_path and os.path.exists(image_path):
            result = post_photo_to_facebook(
                text, page_id, access_token, image_path, scheduled_time=None
            )
        else:
            result = post_to_facebook(
                text, page_id, access_token, scheduled_time=None
            )

        if "id" in result:
            log(f"✅ Шууд нийтлэгдсэн: {result['id']}")
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
