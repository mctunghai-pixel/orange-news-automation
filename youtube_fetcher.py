"""youtube_fetcher.py

Phase 7.3 — Live financial video feed.
Fetches 6 curated YouTube channels (Bloomberg Television, WSJ, Reuters,
Financial Times, CNBC, World Bank Group) via RSS for discovery, then
enriches with the YouTube Data API v3 videos.list endpoint for video
duration (RSS does not expose duration; required for the >3 min filter).

Hybrid γ source strategy (locked in CLAUDE.md Phase 7.3 reservation):
  - RSS:  https://www.youtube.com/feeds/videos.xml?channel_id=UCxxx
          Free, no quota, ~15 most-recent entries per channel.
  - API:  https://www.googleapis.com/youtube/v3/videos?part=contentDetails
          1 unit per video; batch up to 50 IDs per call.
          ~1080 units/day at 2-hour cadence (~10.8% of free 10K quota).

Filters:
  1. Skip clips < 180 seconds (locked decision #3 quality bias).
  2. Skip video IDs in deny_list_videos.json (editorial veto).
  3. Annotate Mongolia-relevant videos (boost flag, NOT exclusion).

Output: youtube_data.json at repo root, consumed by the frontend's
        lib/fetch-youtube.ts via raw GitHub URL.

Author: Azurise AI Master Architect
Date: May 8, 2026
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import feedparser
import requests

# =============================================================================
# CONFIG
# =============================================================================

MNT_TZ = ZoneInfo("Asia/Ulaanbaatar")

# Locked channel list — see CLAUDE.md Phase 7.3 reservation block.
# Bloomberg News (UChirEOpgFCupRAk5etXqPaA) is an optional Phase 7.3.x add-on.
CHANNELS: dict[str, str] = {
    "UCIALMKvObZNtJ6AmdCLP7Lg": "Bloomberg Television",
    "UCK7tptUDHh-RYDsdxO1-5QQ": "WSJ",
    "UChqUTb7kYRX8-EiaN3XFrSQ": "Reuters",
    "UCoUxsWakJucWg46KW5RsvPw": "Financial Times",
    "UCvJJ_dzjViJCoLf5uKUTwoA": "CNBC",
    "UCE9mrcoX-oE-2f1BL-iPPoQ": "World Bank Group",
}

OUTPUT_FILE = "youtube_data.json"
DENY_LIST_FILE = "deny_list_videos.json"

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={uc_id}"
API_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

USER_AGENT = "Mozilla/5.0 (compatible; OrangeNewsYouTubeBot/1.0; +https://www.orangenews.mn)"
HTTP_TIMEOUT = 15

MIN_DURATION_SECONDS = 180  # 3-minute quality bias
MAX_OUTPUT_VIDEOS = 50
API_BATCH_SIZE = 50  # YouTube Data API videos.list cap

MONGOLIA_KEYWORDS = [
    "mongolia", "mongolian", "ulaanbaatar", "ulan bator",
    "монгол", "улаанбаатар", "монголия",
]

# ISO 8601 duration parser (PT#H#M#S form). YouTube uses this for contentDetails.duration.
ISO_DURATION_RE = re.compile(
    r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$"
)


# =============================================================================
# HELPERS
# =============================================================================

def parse_iso_duration(iso: str) -> Optional[int]:
    """Convert PT15M30S → 930 seconds. Returns None on parse failure."""
    if not iso:
        return None
    m = ISO_DURATION_RE.match(iso)
    if not m:
        return None
    h, mn, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + s


def is_mongolia_relevant(title: str, description: str) -> bool:
    haystack = f"{title}\n{description}".lower()
    return any(kw in haystack for kw in MONGOLIA_KEYWORDS)


def load_deny_list() -> set[str]:
    if not os.path.exists(DENY_LIST_FILE):
        return set()
    try:
        with open(DENY_LIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"⚠️ {DENY_LIST_FILE} нь массив биш — алгасав")
            return set()
        return {str(v) for v in data}
    except Exception as e:
        print(f"⚠️ {DENY_LIST_FILE} уншиж чадсангүй: {e}")
        return set()


def extract_thumbnail_url(entry) -> Optional[str]:
    """Best-effort thumbnail URL from feedparser media:thumbnail tag."""
    media_thumb = entry.get("media_thumbnail")
    if media_thumb and isinstance(media_thumb, list) and media_thumb:
        return media_thumb[0].get("url")
    return None


def parse_rss_for_channel(uc_id: str, channel_title: str, errors: list) -> list[dict]:
    """Returns a list of video stubs (no duration yet) for the channel.
    Soft-fails: appends to errors and returns [] on any RSS issue."""
    url = RSS_URL_TEMPLATE.format(uc_id=uc_id)
    try:
        feed = feedparser.parse(
            url, request_headers={"User-Agent": USER_AGENT}
        )
    except Exception as e:
        errors.append(f"{channel_title}: RSS татаж чадсангүй: {type(e).__name__}: {e}")
        return []

    if feed.bozo and not feed.entries:
        errors.append(f"{channel_title}: RSS эвдэрсэн ({feed.bozo_exception})")
        return []

    stubs = []
    for entry in feed.entries:
        video_id = entry.get("yt_videoid") or entry.get("id", "").replace("yt:video:", "")
        if not video_id:
            continue
        media_group = entry.get("media_description") or entry.get("summary") or ""
        stubs.append({
            "id": video_id,
            "title": entry.get("title", "").strip(),
            "description": media_group.strip(),
            "channel_id": uc_id,
            "channel_title": channel_title,
            "published_at": entry.get("published", ""),
            "thumbnail_url": extract_thumbnail_url(entry),
            "watch_url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return stubs


def enrich_with_durations(
    stubs: list[dict], api_key: str, errors: list
) -> dict[str, dict]:
    """Calls YouTube Data API videos.list in batches; returns {video_id: {duration_seconds, duration_iso}}."""
    durations: dict[str, dict] = {}
    ids = [s["id"] for s in stubs]

    for batch_start in range(0, len(ids), API_BATCH_SIZE):
        batch = ids[batch_start:batch_start + API_BATCH_SIZE]
        try:
            r = requests.get(
                API_VIDEOS_URL,
                params={
                    "part": "contentDetails",
                    "id": ",".join(batch),
                    "key": api_key,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            errors.append(f"videos.list batch {batch_start}: {type(e).__name__}: {e}")
            continue

        if r.status_code == 403:
            try:
                err_body = r.json()
                reason = err_body.get("error", {}).get("errors", [{}])[0].get("reason", "")
            except Exception:
                reason = "unknown"
            errors.append(
                f"videos.list HTTP 403 (likely quotaExceeded; reason={reason}); "
                "writing partial data without further enrichment"
            )
            return durations  # bail; downstream filter still runs but with incomplete data

        if not r.ok:
            errors.append(f"videos.list HTTP {r.status_code} {r.reason}")
            continue

        try:
            payload = r.json()
        except Exception as e:
            errors.append(f"videos.list JSON parse failed: {e}")
            continue

        for item in payload.get("items", []):
            vid = item.get("id")
            iso = item.get("contentDetails", {}).get("duration")
            secs = parse_iso_duration(iso) if iso else None
            if vid:
                durations[vid] = {"duration_seconds": secs, "duration_iso": iso}

    return durations


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    started = datetime.now(timezone.utc)
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        sys.exit("❌ YOUTUBE_API_KEY орчны хувьсагч тохируулагдаагүй байна")

    deny = load_deny_list()
    if deny:
        print(f"🚫 Deny list: {len(deny)} video ID")

    all_stubs: list[dict] = []
    errors: list[str] = []
    channels_processed = 0

    for uc_id, channel_title in CHANNELS.items():
        print(f"📺 {channel_title} ({uc_id}) …", end=" ", flush=True)
        stubs = parse_rss_for_channel(uc_id, channel_title, errors)
        print(f"{len(stubs)} entries")
        if stubs:
            channels_processed += 1
        all_stubs.extend(stubs)

    print(f"\n🔍 Enriching {len(all_stubs)} videos with durations …")
    durations = enrich_with_durations(all_stubs, api_key, errors)
    print(f"   ✓ {len(durations)} duration records")

    # Merge + filter pass.
    surviving: list[dict] = []
    filtered_short = 0
    filtered_denied = 0
    filtered_no_duration = 0

    for stub in all_stubs:
        vid = stub["id"]
        if vid in deny:
            filtered_denied += 1
            continue
        d = durations.get(vid, {})
        secs = d.get("duration_seconds")
        if secs is None:
            filtered_no_duration += 1
            continue
        if secs < MIN_DURATION_SECONDS:
            filtered_short += 1
            continue
        stub["duration_seconds"] = secs
        stub["duration_iso"] = d.get("duration_iso")
        stub["mongolia_relevant"] = is_mongolia_relevant(
            stub["title"], stub["description"]
        )
        surviving.append(stub)

    # Sort by published_at desc, cap.
    surviving.sort(key=lambda v: v["published_at"], reverse=True)
    surviving = surviving[:MAX_OUTPUT_VIDEOS]

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    result = {
        "fetched_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_mnt": datetime.now(MNT_TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "channels_processed": channels_processed,
        "videos_total": len(surviving),
        "videos_filtered_short": filtered_short,
        "videos_filtered_denied": filtered_denied,
        "videos_filtered_no_duration": filtered_no_duration,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
        "videos": surviving,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(
        f"\n✅ {OUTPUT_FILE} written | {size_kb:.1f} KB | "
        f"{len(surviving)} videos | {channels_processed}/{len(CHANNELS)} channels"
    )
    if errors:
        print(f"⚠️ {len(errors)} errors:")
        for err in errors:
            print(f"   - {err}")


if __name__ == "__main__":
    main()
