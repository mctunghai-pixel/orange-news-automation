"""
Orange News — Daily Archive Writer (Phase 7.1)
==============================================
Snapshots translated_posts.json into archive/posts_YYYY-MM-DD.json
and upserts an entry into archive/index.json. Date is determined in
MNT (Asia/Ulaanbaatar) so archive boundaries match the editorial day.

Per-day file (wrapped schema):
  {
    "date": "YYYY-MM-DD",
    "generated_at": "ISO8601 UTC",
    "source": "<workflow filename or 'manual'>",
    "posts": [...]
  }

Index file (sorted desc by date):
  [
    {"date": "YYYY-MM-DD", "count": N},
    ...
  ]

Idempotent: re-running for the same date overwrites the per-day file
and upserts the index entry. Safe under both daily workflows
(orange_news.yml + market_watch_live.yml).

Safety: when --date is not explicitly provided, the script verifies
translated_posts.json was last modified within the same MNT day and
skips the write otherwise — guards against archiving stale content
if an upstream phase (translator) failed and left yesterday's file
in place.

Author: Azurise AI Master Architect
Date: May 5, 2026
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MNT_TZ = ZoneInfo("Asia/Ulaanbaatar")

INPUT_FILE = "translated_posts.json"
ARCHIVE_DIR = "archive"
INDEX_FILE = os.path.join(ARCHIVE_DIR, "index.json")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Snapshot translated_posts.json into a daily archive."
    )
    p.add_argument(
        "--source",
        required=True,
        help="Workflow filename that produced this snapshot "
             "(e.g. 'orange_news.yml', 'market_watch_live.yml', or 'manual').",
    )
    p.add_argument(
        "--date",
        default=None,
        help="Override snapshot date (YYYY-MM-DD). Default: today in MNT. "
             "Disables the mtime-freshness guard.",
    )
    return p.parse_args()


def load_posts(path: str) -> list:
    if not os.path.exists(path):
        sys.exit(f"❌ {path} олдсонгүй")
    with open(path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not isinstance(posts, list):
        sys.exit(f"❌ {path} массив биш байна")
    return posts


def freshness_ok(path: str, today_mnt) -> bool:
    """True if the input file was last modified within today (MNT)."""
    mtime_mnt = datetime.fromtimestamp(os.path.getmtime(path), tz=MNT_TZ)
    return mtime_mnt.date() == today_mnt


def write_day_file(date_str: str, source: str, posts: list) -> str:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, f"posts_{date_str}.json")
    payload = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "posts": posts,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def update_index(date_str: str, count: int) -> str:
    entries: list = []
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            try:
                entries = json.load(f)
            except json.JSONDecodeError as e:
                sys.exit(f"❌ {INDEX_FILE} эвдэрсэн: {e}")
        if not isinstance(entries, list):
            sys.exit(f"❌ {INDEX_FILE} массив биш байна")

    entries = [e for e in entries if e.get("date") != date_str]
    entries.append({"date": date_str, "count": count})
    entries.sort(key=lambda e: e["date"], reverse=True)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    return INDEX_FILE


def main() -> None:
    args = parse_args()
    today_mnt = datetime.now(MNT_TZ).date()
    date_str = args.date or today_mnt.isoformat()

    if not args.date and not freshness_ok(INPUT_FILE, today_mnt):
        mtime_mnt = datetime.fromtimestamp(os.path.getmtime(INPUT_FILE), tz=MNT_TZ)
        print(
            f"⚠️ {INPUT_FILE} mtime ({mtime_mnt.date()}) ≠ today MNT ({today_mnt}). "
            f"Skipping archive write to avoid snapshotting stale content."
        )
        return

    posts = load_posts(INPUT_FILE)
    day_path = write_day_file(date_str, args.source, posts)
    idx_path = update_index(date_str, len(posts))

    print(f"✅ archive write: {day_path} ({len(posts)} posts, source={args.source})")
    print(f"✅ index update:  {idx_path}")


if __name__ == "__main__":
    main()
