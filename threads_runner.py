"""Threads publisher runner — hourly cron-driven.

Mirrors ig_runner.py architecture:
  - Hour-based post selection (MNT 08-17 → idx 0-9)
  - Idempotent via logs/threads_publish_state.json
  - DRY_RUN default true (safe), kill switch via THREADS_PUBLISH_ENABLED
  - Per-run status file written to logs/threads_publish_run_status.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

from publishers.caption_adapter import adapt_caption_for_threads
from publishers.threads import ThreadsPublisher

GITHUB_OWNER = "mctunghai-pixel"
GITHUB_REPO = "orange-news-automation"
MEDIA_BRANCH = "media-public"

INPUT_FILE = "translated_posts.json"
LOGS_DIR = "logs"
STATE_FILE = os.path.join(LOGS_DIR, "threads_publish_state.json")
RUN_STATUS_FILE = os.path.join(LOGS_DIR, "threads_publish_run_status.json")

MNT_OFFSET = timedelta(hours=8)
FIRST_POST_HOUR_MNT = 8
LAST_POST_HOUR_MNT = 17
WINDOW_END_HOUR_MNT = 19

HEAD_TIMEOUT_SECONDS = 10
SCHEMA_VERSION = 1


def _log(msg: str) -> None:
    print(f"[threads_runner] {msg}", file=sys.stderr)


def _now_mnt() -> datetime:
    return datetime.now(timezone.utc) + MNT_OFFSET


def _resolve_post_index(now_mnt: datetime) -> int | None:
    hour = now_mnt.hour
    if hour < FIRST_POST_HOUR_MNT or hour > WINDOW_END_HOUR_MNT:
        return None
    return min(hour - FIRST_POST_HOUR_MNT, LAST_POST_HOUR_MNT - FIRST_POST_HOUR_MNT)


def _resolve_override_idx(cli_idx: int | None) -> int | None:
    if cli_idx is not None:
        return cli_idx
    raw = os.environ.get("FORCE_IDX", "").strip()
    if not raw:
        return None
    return int(raw)


def _build_image_url(idx: int, date_str: str) -> str:
    filename = f"post_{idx:02d}_{date_str}.png"
    return (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"{MEDIA_BRANCH}/{filename}"
    )


def _verify_image_url(url: str) -> tuple[bool, str | None]:
    try:
        resp = requests.head(url, timeout=HEAD_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException as e:
        return False, f"HEAD network error: {e}"
    if resp.status_code != 200:
        return False, f"HEAD status {resp.status_code}"
    return True, None


def _kill_switch_engaged() -> tuple[bool, str]:
    """THREADS_PUBLISH_ENABLED repo-variable kill switch (default-disabled)."""
    val = os.environ.get("THREADS_PUBLISH_ENABLED", "").strip().lower()
    if val == "true":
        return False, ""
    if not val:
        return True, "THREADS_PUBLISH_ENABLED not set"
    return True, f'THREADS_PUBLISH_ENABLED="{val}"'


def _is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() != "false"


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"posts": {}, "schema_version": SCHEMA_VERSION}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("posts", {})
        return state
    except Exception:
        return {"posts": {}, "schema_version": SCHEMA_VERSION}


def _save_state(state: dict) -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _write_run_status(status: dict) -> None:
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(RUN_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log(f"⚠ failed to write {RUN_STATUS_FILE}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Threads publisher runner")
    parser.add_argument("--idx", type=int, default=None, help="Override post index")
    args = parser.parse_args()
    cli_idx = args.idx

    status: dict = {
        "exit_path": "unknown",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Kill switch
        engaged, reason = _kill_switch_engaged()
        if engaged:
            _log(f"🛑 kill switch: {reason}")
            status["exit_path"] = "kill_switch"
            status["reason"] = reason
            return 0

        if os.environ.get("ENABLE_THREADS_PUBLISHING") != "1":
            _log("ENABLE_THREADS_PUBLISHING != 1 — exiting")
            status["exit_path"] = "enable_off"
            return 0

        # idx
        now_mnt = _now_mnt()
        date_str = now_mnt.strftime("%Y%m%d")
        status["date_str"] = date_str

        try:
            override_idx = _resolve_override_idx(cli_idx)
        except ValueError as e:
            status["exit_path"] = "force_idx_invalid"
            status["error"] = str(e)
            return 1

        if override_idx is not None:
            idx = override_idx
            _log(f"📌 force_idx override: idx={idx}")
        else:
            idx = _resolve_post_index(now_mnt)
            if idx is None:
                _log(f"MNT hour {now_mnt.hour} outside window")
                status["exit_path"] = "out_of_window"
                status["mnt_hour"] = now_mnt.hour
                return 0

        state_key = f"{date_str}:{idx}"
        status["post_idx"] = idx

        # Idempotency
        state = _load_state()
        if state["posts"].get(state_key, {}).get("ok"):
            _log(f"already published {state_key}")
            status["exit_path"] = "already_published_local"
            status["external_id"] = state["posts"][state_key].get("external_id")
            return 0

        # Load posts
        if not os.path.exists(INPUT_FILE):
            status["exit_path"] = "input_missing"
            status["error"] = f"{INPUT_FILE} not found"
            return 1
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if idx >= len(posts):
            _log(f"idx {idx} out of range ({len(posts)} posts)")
            status["exit_path"] = "idx_out_of_range"
            status["posts_total"] = len(posts)
            return 0
        post = posts[idx]

        # Image URL (same media-public branch as IG)
        image_url = _build_image_url(idx, date_str)
        _log(f"image URL: {image_url}")
        url_ok, url_err = _verify_image_url(image_url)
        if not url_ok:
            _log(f"❌ image URL not reachable: {url_err}")
            status["exit_path"] = "image_url_unreachable"
            status["error"] = url_err
            state["posts"][state_key] = {
                "ok": False, "error": url_err,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _save_state(state)
            return 1

        caption = adapt_caption_for_threads(post)
        _log(f"caption ({len(caption)} chars):")
        for line in caption.splitlines():
            _log(f"  | {line}")

        if _is_dry_run():
            _log("=== DRY_RUN: not publishing ===")
            status["exit_path"] = "dry_run"
            status["caption_len"] = len(caption)
            return 0

        # Publish
        started_at = datetime.now(timezone.utc).isoformat()
        publisher = ThreadsPublisher()
        result = publisher.publish(image_url, caption)

        state["posts"][state_key] = {
            "ok": result.ok,
            "external_id": result.external_id,
            "error": result.error,
            "attempts": result.attempts,
            "timestamp": started_at,
        }
        _save_state(state)

        status["attempts"] = result.attempts
        if not result.ok:
            _log(f"❌ publish failed: {result.error}")
            status["exit_path"] = "publish_failure"
            status["error"] = result.error
            return 1

        _log(f"✅ published: {result.external_id}")
        status["exit_path"] = "publish_success"
        status["external_id"] = result.external_id
        return 0

    except Exception as e:
        _log(f"💥 unhandled exception: {e}")
        status["exit_path"] = "exception"
        status["error"] = f"{type(e).__name__}: {e}"
        return 1
    finally:
        _write_run_status(status)


if __name__ == "__main__":
    sys.exit(main())
