"""
reels_runner.py — publish 4 Aravt News Reels a day to the Facebook Page.

Plan for each day (from translated_posts.json):
  slot 0  10:30 MNT  Market Watch reel
  slot 1  13:30 MNT  news #1      (first 3 non-Market-Watch stories)
  slot 2  16:30 MNT  news #2
  slot 3  19:30 MNT  news #3
Each run publishes at most ONE reel: the earliest due slot that is not done yet
(so a late or failed run catches up on the next one). State lives in
logs/reels_publish_state.json, which the workflow commits back.

Gates:  REELS_PUBLISH_ENABLED repo variable ("false" = off), DRY_RUN=true (render only).
FB API: POST /{page}/video_reels start → upload to rupload → finish (PUBLISHED).
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import reel_maker as RM
from brand_card import gradient_photo

MNT = ZoneInfo("Asia/Ulaanbaatar")
GRAPH = "https://graph.facebook.com/v21.0"
STATE = "logs/reels_publish_state.json"
STATUS = "logs/reels_publish_run_status.json"
SLOT_HOURS = [10, 13, 16, 19]
MEDIA_RAW = "https://raw.githubusercontent.com/mctunghai-pixel/orange-news-automation/media-public"


def log(msg):
    print(f"[reels] {msg}", flush=True)


def write_status(**kw):
    os.makedirs("logs", exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(kw, f, ensure_ascii=False, indent=2)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs("logs", exist_ok=True)
    keep = dict(sorted(st.items())[-14:])          # two weeks of history is plenty
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=2)


def plan(posts):
    mw = next((i for i, p in enumerate(posts) if p.get("is_market_watch") or p.get("type") == "market_watch"), None)
    news = [i for i, p in enumerate(posts) if i != mw and p.get("headline")][:3]
    return [("market", mw)] + [("news", i) for i in news]


def photo_for(post, tmp):
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    pid = post.get("photo_id")
    if str(pid or "").startswith("wm:") and post.get("photo_url"):     # fix30: Commons photo
        try:
            img = requests.get(post["photo_url"], headers={"User-Agent": "AravtNewsBot/1.0 (https://www.aravtnews.com)"}, timeout=30)
            img.raise_for_status()
            path = os.path.join(tmp, "commons.jpg")
            open(path, "wb").write(img.content)
            return path
        except Exception as e:
            log(f"commons {pid}: {e}")
    if key and pid and not str(pid).startswith("wm:"):
        try:
            r = requests.get("https://pixabay.com/api/", params={"key": key, "id": pid}, timeout=15)
            hits = r.json().get("hits", [])
            if hits:
                img = requests.get(hits[0].get("largeImageURL") or hits[0]["webformatURL"], timeout=30)
                img.raise_for_status()
                path = os.path.join(tmp, f"px_{pid}.jpg")
                open(path, "wb").write(img.content)
                return path
        except Exception as e:
            log(f"pixabay id {pid}: {e}")
    if key:
        try:
            from photo_fetcher import fetch_photo
            path, _ = fetch_photo(dict(post), set(), out_dir=tmp)
            if path:
                return path
        except Exception as e:
            log(f"pixabay search: {e}")
    return gradient_photo((post.get("category") or "finance").lower(), os.path.join(tmp, "bg.jpg"))


def fb_publish_reel(page_id, token, video_path, description):
    r = requests.post(f"{GRAPH}/{page_id}/video_reels",
                      data={"upload_phase": "start", "access_token": token}, timeout=30)
    r.raise_for_status()
    vid = r.json()["video_id"]
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/video-upload/v21.0/{vid}",
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                           data=f, timeout=300)
    up.raise_for_status()
    if not up.json().get("success"):
        raise RuntimeError(f"upload failed: {up.text[:300]}")
    fin = requests.post(f"{GRAPH}/{page_id}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": description, "access_token": token}, timeout=60)
    fin.raise_for_status()
    if not fin.json().get("success", True):
        raise RuntimeError(f"finish failed: {fin.text[:300]}")
    return vid


def main():
    now = datetime.now(MNT)
    date = now.strftime("%Y-%m-%d")
    dry = os.environ.get("DRY_RUN", "").lower() == "true"
    enabled = os.environ.get("REELS_PUBLISH_ENABLED", "").strip().lower()
    if enabled in ("false", "0", "no", "off") and not dry:
        log("REELS_PUBLISH_ENABLED=false → off")
        write_status(exit_path="kill_switch", date=date)
        return 0
    try:
        posts = json.load(open("translated_posts.json", encoding="utf-8"))
    except Exception as e:
        write_status(exit_path="input_missing", error=str(e), date=date)
        return 0
    gen = str(posts[0].get("generated_date") or "")[:10] if posts else ""
    if gen and gen != date and not dry:
        log(f"translated_posts.json is from {gen}, not today ({date}) — waiting for today's run")
        write_status(exit_path="stale_posts", date=date, generated=gen)
        return 0

    st = load_state()
    done = st.setdefault(date, {})
    force = os.environ.get("FORCE_SLOT", "").strip()
    slots = plan(posts)
    if force:
        slot = int(force)
    else:
        due = [i for i, h in enumerate(SLOT_HOURS) if now.hour >= h and str(i) not in done and i < len(slots)]
        if not due:
            log(f"nothing due at {now:%H:%M} (done: {sorted(done)})")
            write_status(exit_path="nothing_due", date=date, done=sorted(done))
            return 0
        slot = due[0]
    kind, idx = slots[slot]
    if os.environ.get("CHECK_ONLY"):          # fix20: cheap pre-check before installing ffmpeg
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            open(out, "a").write("due=true\n")
        log(f"slot {slot} due ({kind})")
        return 0
    if idx is None:
        done[str(slot)] = {"skipped": "no market watch"}
        save_state(st)
        write_status(exit_path="skipped", slot=slot, date=date)
        return 0
    post = posts[idx]
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, f"reel_{date}_{slot}.mp4")
    seed = int(now.strftime("%j")) * 4 + slot
    if kind == "market":
        mw = os.path.join(tmp, "mw.png")
        r = requests.get(f"{MEDIA_RAW}/post_{idx:02d}_{now:%Y%m%d}.png", timeout=30)
        if r.status_code != 200:
            done[str(slot)] = {"skipped": f"market watch card HTTP {r.status_code}"}
            save_state(st)
            write_status(exit_path="skipped", slot=slot, date=date, error=f"mw card {r.status_code}")
            return 0
        open(mw, "wb").write(r.content)
        RM.make_market_reel(mw, out, seed)
        desc = (f"📊 Өнөөдрийн зах зээл — хувьцаа, крипто, алт, ханш нэг дор.\n\n"
                f"👉 FOLLOW дараад өглөө бүр Market Watch-оо аваарай\n🌐 {RM.BRAND.SITE_URL}\n"
                f"📨 Telegram: {RM.BRAND.TELEGRAM}\n\n{RM.BRAND.HASHTAG} {RM.BRAND.MW_HASHTAG} #Markets")
    else:
        RM.make_news_reel(post, photo_for(post, tmp), out, seed)
        desc = RM.caption(post)
    log(f"slot {slot} ({kind}, idx {idx}) rendered {os.path.getsize(out)//1024} KB")
    keep = os.environ.get("REEL_KEEP_DIR")
    if keep:                                  # workflow uploads this as an artifact for review
        import shutil
        os.makedirs(keep, exist_ok=True)
        shutil.copy(out, keep)
    if dry:
        os.makedirs("logs", exist_ok=True)
        write_status(exit_path="dry_run", slot=slot, post_idx=idx, date=date, caption=desc)
        log("DRY_RUN — not publishing\n" + desc)
        return 0
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_ACCESS_TOKEN")
    try:
        vid = fb_publish_reel(page, token, out, desc)
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")[:400]
        log(f"❌ publish failed: {e} {body}")
        write_status(exit_path="publish_failure", slot=slot, post_idx=idx, date=date, error=f"{e} {body}")
        # fix19: keep the last error in the committed state (slot stays "not done", so it is retried)
        done[f"err{slot}"] = {"at": now.strftime("%H:%M"), "error": f"{e} {body}"[:300]}
        save_state(st)
        return 1
    done[str(slot)] = {"video_id": vid, "idx": idx, "kind": kind, "at": now.strftime("%H:%M")}
    save_state(st)
    write_status(exit_path="publish_success", slot=slot, post_idx=idx, external_id=vid, date=date)
    log(f"✅ published reel video_id={vid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
