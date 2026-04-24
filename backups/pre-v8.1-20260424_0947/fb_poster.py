"""
Orange News — Facebook Poster v7 FINAL
=======================================
Бүх засвар нэгтгэсэн эцсийн хувилбар

Шинэчлэлт:
1. ✅ full_post талбарыг priority-оор унших
2. ✅ Хуучин format_post() функц markdown # тэмдэгтэй гарчгийг устгана
3. ✅ Эхний пост шууд (Market Watch), бусад нь 1 цагийн зайтай scheduling
4. ✅ Facebook scheduled_publish_time параметр ашиглана
5. ✅ Fallback: full_post байхгүй бол headline + body + footer угсарна
6. ✅ Монгол цагаар лог бичнэ
"""

import argparse
import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta

# =============================================================================
# CONFIG
# =============================================================================

INPUT_FILE = "translated_posts.json"
LOG_FILE = "pipeline_log.txt"
DELAY_SECS = 3600  # 1 цаг
FB_API_URL = "https://graph.facebook.com/v19.0"
MARKET_WATCH_IMAGE = "assets/market_watch_thumbnail.png"

# Footer template (v8 Bloomberg-style — fallback-д ашиглана)
FOOTER_LINKS = """

━━━━━━━━━━━━━━━━━━━━━━

🌐 www.orangenews.mn

📘 facebook.com/orangenews.mn
📷 instagram.com/orangenews.official
🧵 threads.net/@orangenews.official"""

# =============================================================================
# image_generator холболт
# =============================================================================

try:
    from image_generator import generate_image as _gen_img
    IMAGE_GEN_AVAILABLE = True
except ImportError:
    IMAGE_GEN_AVAILABLE = False


# =============================================================================
# ТУСЛАХ ФУНКЦ
# =============================================================================

def log(message):
    """Монгол цагаар лог бичих"""
    # UTC + 8 = Монгол цаг
    mn_time = datetime.now(timezone.utc) + timedelta(hours=8)
    timestamp = mn_time.strftime("%Y-%m-%d %H:%M:%S MNT")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


def get_post_image(post: dict, idx: int):
    """Постын зургийн path буцаана"""
    # Market Watch
    is_mw = (
        post.get("use_market_watch_image", False)
        or post.get("type") == "market_watch"
        or post.get("category") == "market_watch"
    )
    if is_mw:
        if os.path.exists(MARKET_WATCH_IMAGE):
            return MARKET_WATCH_IMAGE
        # Fallback: үүсгэсэн зургийг ашиглах
        today = datetime.now().strftime("%Y%m%d")
        candidate = f"assets/generated/post_{idx:02d}_{today}.png"
        if os.path.exists(candidate):
            return candidate
        return None

    # 1. Өмнө үүссэн файл
    today = datetime.now().strftime("%Y%m%d")
    candidate = f"assets/generated/post_{idx:02d}_{today}.png"
    if os.path.exists(candidate):
        return candidate

    # 2. image_path талбараас
    if post.get("image_path") and os.path.exists(post["image_path"]):
        return post["image_path"]

    # 3. image_generator-р шинээр үүсгэнэ
    if IMAGE_GEN_AVAILABLE:
        try:
            headline = post.get("headline") or post.get("title", "")
            category = post.get("category", "FINANCE").upper()
            img_url = post.get("image_url", "")
            article_url = post.get("original_url") or post.get("url", "")
            path = _gen_img(
                headline=headline,
                category=category,
                image_url=img_url,
                article_url=article_url,
                index=idx,
            )
            if path and os.path.exists(path):
                return path
        except Exception as e:
            log(f"  ⚠️ Image gen алдаа: {e}")

    return None


def get_page_token(user_token, page_id):
    """User token → Page token"""
    import urllib.request, json as _json, ssl
    url = f"{FB_API_URL}/me/accounts?access_token={user_token}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=30) as r:
            data = _json.loads(r.read())
        for page in data.get("data", []):
            if page["id"] == page_id:
                return page.get("access_token", user_token)
    except Exception as e:
        log(f"  ⚠️ get_page_token алдаа: {e}")
    return user_token


def check_market_watch_exists_today(page_id, access_token) -> bool:
    """
    v8: Query FB Page posts in the last 24h.
    Return True if an Orange Market Watch post already published today.

    Fail-open: on any API/network error, return False so the pipeline
    proceeds and schedules a new MW rather than silently missing a day.
    """
    since_epoch = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
    url = f"{FB_API_URL}/{page_id}/posts"
    params = {
        "fields": "message,created_time",
        "since": since_epoch,
        "access_token": access_token,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        posts = r.json().get("data", [])
        for post in posts:
            msg = post.get("message", "") or ""
            if "ORANGE MARKET WATCH" in msg:
                created = post.get("created_time", "?")
                log(f"  ⏭️  MW already published in last 24h (created: {created})")
                return True
        log(f"  ✅ No MW in last 24h — OK to schedule new MW")
        return False
    except Exception as e:
        log(f"  ⚠️  MW de-dupe check failed ({type(e).__name__}: {e}) — fail-open, proceeding")
        return False


def post_to_facebook(text, page_id, access_token, scheduled_time=None):
    """Зураггүй текст пост"""
    url = f"{FB_API_URL}/{page_id}/feed"
    data = {"message": text, "access_token": access_token}
    if scheduled_time:
        data["scheduled_publish_time"] = str(int(scheduled_time))
        data["published"] = "false"

    r = requests.post(url, data=data, timeout=30)
    return r.json()


def post_photo_to_facebook(text, page_id, access_token, image_path, scheduled_time=None):
    """Зурагтай пост"""
    url = f"{FB_API_URL}/{page_id}/photos"

    with open(image_path, "rb") as img:
        data = {"caption": text, "access_token": access_token}
        if scheduled_time:
            data["scheduled_publish_time"] = str(int(scheduled_time))
            data["published"] = "false"

        r = requests.post(
            url,
            data=data,
            files={"source": (os.path.basename(image_path), img, "image/png")},
            timeout=60
        )
    return r.json()


def format_post(post):
    """
    Пост-ын ЭЦСИЙН бүрэн текст буцаах.
    Priority:
      1. full_post (v7 translator-ийн шинэ талбар) — бэлэн бүрэн текст
      2. post_text (хэрвээ footer + hashtags оролцсон бол)
      3. Manual build: badge + headline + body + footer угсрах
    """
    import re

    # PRIORITY 1: full_post талбар
    if post.get("full_post"):
        return post["full_post"]

    # PRIORITY 2: post_text full текст байж болзошгүй
    post_text = post.get("post_text", "")
    if post_text and "orangenews.mn" in post_text and "#OrangeNews" in post_text:
        return post_text

    # PRIORITY 3: Manual build
    # Markdown # гарчиг устгах
    post_text_clean = re.sub(r"^#+\s*", "", post_text, flags=re.MULTILINE) if post_text else ""

    # Хиймэл төгсгөл устгах
    for pattern in [
        r"Та үүнийг юу гэж бодож байна\?.*$",
        r"Сэтгэгдэлээ хуваалцаарай.*$",
        r"Монголын хөрөнгө оруулагчдад.*$",
        r"Монголд хамааралтай нь:.*$",
        r"👇.*$",
    ]:
        post_text_clean = re.sub(pattern, "", post_text_clean, flags=re.MULTILINE | re.DOTALL)

    badge = post.get("badge", "🟠 BUSINESS")
    headline = post.get("headline", "")
    body = post.get("body_only") or post_text_clean
    hashtags = post.get("hashtags", ["#OrangeNews", "#Finance"])
    hashtag_line = " ".join(hashtags) if isinstance(hashtags, list) else hashtags

    return f"""{badge}

{headline}

{body}
{FOOTER_LINKS}

{hashtag_line}""".strip()


# =============================================================================
# MAIN
# =============================================================================

def run(live, use_scheduling=True, skip_market_watch=False):
    mode = "LIVE" if live else "TEST"
    log(f"{'='*50}")
    log(f"🍊 Orange News FB Poster v7 FINAL | Mode: {mode}")
    log(f"{'='*50}")

    if not os.path.exists(INPUT_FILE):
        log(f"❌ {INPUT_FILE} олдсонгүй")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)

    log(f"📰 {len(posts)} пост олдлоо")

    if live:
        page_id = os.environ.get("FB_PAGE_ID")
        user_token = os.environ.get("FB_ACCESS_TOKEN")
        if not page_id or not user_token:
            log("❌ FB_PAGE_ID эсвэл FB_ACCESS_TOKEN олдсонгүй!")
            return
        access_token = get_page_token(user_token, page_id)
    else:
        page_id = access_token = "TEST"

    # =========================================================================
    # SCHEDULING v7.1 — Бүх постыг MNT fixed цагаар Facebook-д schedule
    # =========================================================================
    # Өмнөх зан төлөв: idx=0 шууд → GHA саатал шууд пост дээр тусна.
    # Шинэ зан төлөв: бүх пост Facebook-д schedule → GHA саатал нөлөөлөхгүй.
    #
    # Хуваарь: Post 1 → 08:00 MNT, Post 2 → 09:00 MNT, ..., Post 10 → 17:00 MNT
    # Pipeline-г 06:00 MNT гэх мэт эрт ажиллуулвал бүх пост цагтаа гарна.
    # =========================================================================
    FIRST_POST_HOUR_MNT = 8  # 08:00 MNT
    HOUR_GAP = 1             # Постын хоорондох цагийн зай
    MNT_OFFSET = timedelta(hours=8)

    now_utc = datetime.now(timezone.utc)
    now_mnt = now_utc + MNT_OFFSET

    # Өнөөдрийн 08:00 MNT (UTC форматаар)
    first_post_mnt = now_mnt.replace(
        hour=FIRST_POST_HOUR_MNT, minute=0, second=0, microsecond=0
    )
    # Хэрвээ 08:00 MNT өнгөрсөн бол (жишээ нь pipeline 11:00-д ажилласан),
    # маргаашын 08:00 MNT-ээр эхлүүлнэ. Иначе өнөөдрийн 08:00-аас.
    if first_post_mnt <= now_mnt + timedelta(minutes=11):
        first_post_mnt = first_post_mnt + timedelta(days=1)
        log(f"⚠️ 08:00 MNT өнгөрсөн → маргаашаар schedule хийнэ")

    first_post_utc = first_post_mnt - MNT_OFFSET
    success = failed = 0

    for idx, post in enumerate(posts):
        text = format_post(post)
        if not text:
            log(f"[{idx+1}/{len(posts)}] ⚠️ Текстгүй, алгасав")
            continue

        is_mw = (post.get("use_market_watch_image", False) or
                 post.get("category") == "market_watch" or
                 post.get("type") == "market_watch" or
                 idx == 0)
        if skip_market_watch and is_mw:
            log(f"[{idx+1}/{len(posts)}] ⏭️ Skipped Market Watch (handled by fb_poster_live.py)")
            continue

        # v8: MW de-dupe — avoid double-posting if fb_poster_live.py already ran today
        if live and is_mw and check_market_watch_exists_today(page_id, access_token):
            log(f"[{idx+1}/{len(posts)}] ⏭️  MW already exists today — skipping this slot")
            continue

        label = "📊 MARKET WATCH" if is_mw else "📰 NEWS"

        # Бүх постыг schedule хийнэ (шууд биш)
        scheduled_utc = first_post_utc + timedelta(hours=idx * HOUR_GAP)
        # Facebook minimum = 10 минут ирээдүй (safety check)
        min_future = now_utc + timedelta(minutes=11)
        if scheduled_utc < min_future:
            scheduled_utc = min_future

        scheduled_time = scheduled_utc.timestamp() if use_scheduling else None
        if scheduled_time:
            mnt_display = (scheduled_utc + MNT_OFFSET).strftime("%m-%d %H:%M")
            schedule_label = f"⏰ {mnt_display} MNT"
        else:
            schedule_label = "⚡ Шууд"

        log(f"")
        log(f"[{idx+1}/{len(posts)}] {label} | {schedule_label}")
        log(f"  📝 {post.get('headline', '')[:60]}")
        log(f"  📏 Текст: {len(text)} тэмдэгт")

        if live:
            try:
                image_path = get_post_image(post, idx)

                if image_path and os.path.exists(image_path):
                    log(f"  🖼️  Зураг: {os.path.basename(image_path)}")
                    result = post_photo_to_facebook(
                        text, page_id, access_token, image_path,
                        scheduled_time=scheduled_time
                    )
                else:
                    log(f"  📝 Зураггүй текст пост")
                    result = post_to_facebook(
                        text, page_id, access_token,
                        scheduled_time=scheduled_time
                    )

                if "id" in result:
                    status = "✅ Шууд нийтлэгдсэн" if scheduled_time is None else f"✅ Scheduled → {schedule_label}"
                    log(f"  {status}: {result['id']}")
                    success += 1
                else:
                    err = result.get('error', {}).get('message', str(result))
                    log(f"  ❌ FB API: {err}")
                    failed += 1

                # Rate limit
                time.sleep(2)

            except Exception as e:
                log(f"  ❌ Exception: {e}")
                failed += 1
        else:
            # TEST mode
            log(f"  ✓ TEST — {len(text)} тэмдэгт")
            print(f"\n{'-'*60}")
            print(text[:500] + "..." if len(text) > 500 else text)
            print(f"{'-'*60}")
            success += 1

    log(f"\nDONE | {success} амжилттай, {failed} алдаа | {mode}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Бодит нийтлэх")
    parser.add_argument(
        "--skip-market-watch",
        action="store_true",
        help="Market Watch постыг алгасах (fb_poster_live.py-д үлдээх)"
    )
    args = parser.parse_args()
    run(live=args.live, skip_market_watch=args.skip_market_watch)
