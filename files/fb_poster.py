import argparse, json, os, time, requests
from datetime import datetime, timezone

INPUT_FILE         = "translated_posts.json"
LOG_FILE           = "pipeline_log.txt"
DELAY_SECS         = 3600
FB_API_URL         = "https://graph.facebook.com/v19.0"
MARKET_WATCH_IMAGE = "assets/market_watch_thumbnail.png"

# ── image_generator холболт ───────────────────────────────────────────────────
try:
    from image_generator import generate_image as _gen_img
    IMAGE_GEN_AVAILABLE = True
except ImportError:
    IMAGE_GEN_AVAILABLE = False

def get_post_image(post: dict, idx: int) -> "str | None":
    """
    Постын зургийн path буцаана.
    Priority:
      1. assets/generated/post_NN_YYYYMMDD.png — image_generator-р үүсгэсэн файл
      2. image_generator-р шинээр үүсгэнэ (article_url ашиглан OG зураг татна)
      3. Market Watch → MARKET_WATCH_IMAGE
      4. None (текст пост)
    """
    # Market Watch
    is_mw = (
        post.get("use_market_watch_image", False)
        or post.get("type") == "market_watch"
        or post.get("category") == "market_watch"
    )
    if is_mw:
        return MARKET_WATCH_IMAGE if os.path.exists(MARKET_WATCH_IMAGE) else None

    # 1. Өмнө үүссэн файл байгаа эсэх шалга
    today = datetime.now().strftime("%Y%m%d")
    candidate = f"assets/generated/post_{idx:02d}_{today}.png"
    if os.path.exists(candidate):
        return candidate

    # 2. image_generator-р шинээр үүсгэнэ
    if IMAGE_GEN_AVAILABLE:
        try:
            headline    = post.get("headline") or post.get("title", "")
            category    = post.get("category", "FINANCE").upper()
            img_url     = post.get("image_url", "")
            article_url = post.get("url", "")
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
            log(f"  ⚠️  Image gen алдаа: {e}")

    return None

def log(message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_page_token(user_token, page_id):
    import urllib.request, json as _json, ssl
    url = f"https://graph.facebook.com/v19.0/me/accounts?access_token={user_token}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, context=ctx) as r:
        data = _json.loads(r.read())
    for page in data.get("data", []):
        if page["id"] == page_id:
            return page.get("access_token", user_token)
    return user_token

def post_to_facebook(text, page_id, access_token):
    url = f"{FB_API_URL}/{page_id}/feed"
    r = requests.post(url, data={"message": text, "access_token": access_token}, timeout=30)
    return r.json()

def post_photo_to_facebook(text, page_id, access_token, image_path):
    url = f"{FB_API_URL}/{page_id}/photos"
    with open(image_path, "rb") as img:
        r = requests.post(
            url,
            data={"caption": text, "access_token": access_token},
            files={"source": ("thumbnail.png", img, "image/png")},
            timeout=30
        )
    return r.json()

def format_post(post):
    if post.get("post_text"):
        return post["post_text"]
    parts = [post.get("headline",""), "", post.get("post_text",""), "", " ".join(post.get("hashtags",[]))]
    return "\n".join(parts).strip()

def run(live):
    mode = "LIVE" if live else "TEST"
    log(f"{'='*50}")
    log(f"🍊 Orange News FB Poster | Mode: {mode}")
    log(f"{'='*50}")

    if not os.path.exists(INPUT_FILE):
        log(f"❌ {INPUT_FILE} олдсонгүй")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)

    log(f"📰 {len(posts)} пост олдлоо")

    if live:
        page_id      = os.environ.get("FB_PAGE_ID")
        user_token   = os.environ.get("FB_ACCESS_TOKEN")
        access_token = get_page_token(user_token, page_id)
    else:
        page_id = access_token = "TEST"

    success = failed = 0

    for idx, post in enumerate(posts):
        text = format_post(post)
        if not text:
            continue

        is_mw = post.get("use_market_watch_image", False) or \
                post.get("category") == "market_watch" or idx == 0
        label = "📊 MARKET WATCH" if is_mw else "📰 NEWS"
        log(f"\n[{idx+1}/{len(posts)}] {label}: {post.get('headline','')[:55]}...")

        if live:
            try:
                image_path = get_post_image(post, idx)
                if image_path and os.path.exists(image_path):
                    log(f"  🖼️  Зурагтай пост → {os.path.basename(image_path)}")
                    result = post_photo_to_facebook(text, page_id, access_token, image_path)
                else:
                    log("  📝 Текст пост (зураг байхгүй)")
                    result = post_to_facebook(text, page_id, access_token)

                if "id" in result:
                    log(f"  ✅ ID: {result['id']}")
                    success += 1
                else:
                    log(f"  ❌ {result.get('error',{}).get('message', str(result))}")
                    failed += 1
            except Exception as e:
                log(f"  ❌ {e}")
                failed += 1
        else:
            log(f"  ✓ TEST — {len(text)} тэмдэгт")
            print(f"\n{'-'*50}\n{text[:200]}...\n{'-'*50}")
            success += 1

        if idx < len(posts) - 1:
            if live:
                log(f"  ⏳ 1 цаг хүлээж байна...")
                time.sleep(DELAY_SECS)
            else:
                log(f"  🕐 [TEST] 1 цагийн дараа")

    log(f"\nDONE | {success} амжилттай, {failed} алдаа | {mode}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    run(live=args.live)
