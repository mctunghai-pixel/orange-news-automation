"""IG publisher runner — invoked by .github/workflows/ig_publisher_hourly.yml.

Determines current MNT hour, picks the corresponding post index, and publishes
that single post to Instagram. Idempotent via logs/ig_publish_state.json.

Hour-to-index mapping (MNT, posts go live at the hour they're scheduled):
  08:00 (UTC 00:00) -> post 0  (Market Watch)
  09:00 (UTC 01:00) -> post 1
  10:00 (UTC 02:00) -> post 2
  ...
  17:00 (UTC 09:00) -> post 9

Gated by ENABLE_IG_PUBLISHING env var (must equal "1" to actually publish).
Slack alerts at >=3 failures per day (deduped via state file).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

from publishers.caption_adapter import adapt_caption_for_ig
from publishers.instagram import InstagramPublisher, write_ig_publish_log

GITHUB_OWNER = "mctunghai-pixel"
GITHUB_REPO = "orange-news-automation"
MEDIA_BRANCH = "media-public"

INPUT_FILE = "translated_posts.json"
LOGS_DIR = "logs"
STATE_FILE = os.path.join(LOGS_DIR, "ig_publish_state.json")

MNT_OFFSET = timedelta(hours=8)
FIRST_POST_HOUR_MNT = 8
LAST_POST_HOUR_MNT = 17

SLACK_FAILURE_THRESHOLD = 3
SCHEMA_VERSION = 1
HEAD_TIMEOUT_SECONDS = 10
SLACK_TIMEOUT_SECONDS = 10


def _log(msg: str) -> None:
    print(f"[ig_runner] {msg}", file=sys.stderr)


def _now_mnt() -> datetime:
    return datetime.now(timezone.utc) + MNT_OFFSET


def _resolve_post_index(now_mnt: datetime) -> int | None:
    hour = now_mnt.hour
    if hour < FIRST_POST_HOUR_MNT or hour > LAST_POST_HOUR_MNT:
        return None
    return hour - FIRST_POST_HOUR_MNT


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


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "posts": {},
            "meta": {"slack_alerted": {}, "schema_version": SCHEMA_VERSION},
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("posts", {})
    state.setdefault("meta", {})
    state["meta"].setdefault("slack_alerted", {})
    state["meta"].setdefault("schema_version", SCHEMA_VERSION)
    return state


def _save_state(state: dict) -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _append_log_entry(date_str: str, entry: dict, started_at: str) -> str:
    log_path = os.path.join(LOGS_DIR, f"ig_publish_log_{date_str}.json")
    finished_at = datetime.now(timezone.utc).isoformat()
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["results"].append(entry)
        payload["finished_at"] = finished_at
        ok = sum(1 for e in payload["results"] if e.get("ok"))
        payload["summary"] = {
            "total": len(payload["results"]),
            "ok": ok,
            "failed": len(payload["results"]) - ok,
        }
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    else:
        write_ig_publish_log(
            entries=[entry],
            date_str=date_str,
            started_at=started_at,
            finished_at=finished_at,
        )
    return log_path


def _slack_alert_if_threshold(date_str: str, state: dict, log_path: str) -> None:
    if state["meta"]["slack_alerted"].get(date_str):
        return
    if not os.path.exists(log_path):
        return
    with open(log_path, "r", encoding="utf-8") as f:
        log_data = json.load(f)
    failed_count = log_data.get("summary", {}).get("failed", 0)
    if failed_count < SLACK_FAILURE_THRESHOLD:
        return
    failed_indices = sorted(
        e["post_index"] for e in log_data.get("results", []) if not e.get("ok")
    )
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        _log("SLACK_WEBHOOK_URL not set — skipping alert")
        return
    iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    text = (
        f"🚨 IG publishing: {failed_count} failures on {iso_date} "
        f"(posts: {','.join(str(i) for i in failed_indices)})\n"
        f"Investigate: token expiry / IG quota / image URL accessibility\n"
        f"Logs: {log_path}"
    )
    try:
        requests.post(webhook, json={"text": text}, timeout=SLACK_TIMEOUT_SECONDS)
        state["meta"]["slack_alerted"][date_str] = True
        _save_state(state)
        _log(f"Slack alert sent ({failed_count} failures)")
    except requests.RequestException as e:
        _log(f"Slack alert failed: {e}")


def main() -> int:
    if os.environ.get("ENABLE_IG_PUBLISHING") != "1":
        _log("ENABLE_IG_PUBLISHING != 1 — exiting without publish")
        return 0

    now_mnt = _now_mnt()
    date_str = now_mnt.strftime("%Y%m%d")
    idx = _resolve_post_index(now_mnt)
    if idx is None:
        _log(f"current MNT hour {now_mnt.hour} outside window — exiting")
        return 0
    state_key = f"{date_str}:{idx}"
    _log(f"MNT now: {now_mnt.isoformat()} -> post idx {idx} (key={state_key})")

    state = _load_state()
    if state["posts"].get(state_key, {}).get("ok"):
        _log(f"already published {state_key} — skipping")
        return 0

    if not os.path.exists(INPUT_FILE):
        _log(f"❌ {INPUT_FILE} not found — translator hasn't run today")
        return 1
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if idx >= len(posts):
        _log(f"idx {idx} out of range (only {len(posts)} posts) — exiting")
        return 0
    post = posts[idx]

    image_url = _build_image_url(idx, date_str)
    _log(f"image URL: {image_url}")
    url_ok, url_err = _verify_image_url(image_url)
    if not url_ok:
        _log(f"❌ image URL not reachable: {url_err}")
        started_at = datetime.now(timezone.utc).isoformat()
        entry = {
            "post_index": idx,
            "ok": False,
            "external_id": None,
            "attempts": 0,
            "error": f"image URL not reachable: {url_err}",
            "timestamp": started_at,
        }
        log_path = _append_log_entry(date_str, entry, started_at)
        state["posts"][state_key] = {
            "ok": False,
            "error": entry["error"],
            "timestamp": started_at,
        }
        _save_state(state)
        _slack_alert_if_threshold(date_str, state, log_path)
        return 1

    caption = adapt_caption_for_ig(post)
    started_at = datetime.now(timezone.utc).isoformat()
    publisher = InstagramPublisher()
    result = publisher.publish(image_url, caption)

    entry = {
        "post_index": idx,
        "ok": result.ok,
        "external_id": result.external_id,
        "attempts": result.attempts,
        "error": result.error,
        "timestamp": started_at,
    }
    log_path = _append_log_entry(date_str, entry, started_at)

    state["posts"][state_key] = {
        "ok": result.ok,
        "external_id": result.external_id,
        "error": result.error,
        "timestamp": started_at,
    }
    _save_state(state)

    _slack_alert_if_threshold(date_str, state, log_path)

    if not result.ok:
        _log(f"❌ publish failed: {result.error}")
        return 1
    _log(f"✅ published: {result.external_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
