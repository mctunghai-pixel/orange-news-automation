"""IG publisher runner — invoked by .github/workflows/ig_publisher_hourly.yml.

Determines current MNT hour, picks the corresponding post index, and publishes
that single post to Instagram. Idempotent via logs/ig_publish_state.json.

Hour-to-index mapping (MNT, posts go live at the hour they're scheduled):
  08:00 (UTC 00:00) -> post 0  (Market Watch)
  09:00 (UTC 01:00) -> post 1
  10:00 (UTC 02:00) -> post 2
  ...
  17:00 (UTC 09:00) -> post 9

Gating (defense in depth, in this order):
  - IG_PUBLISH_ENABLED env (must equal "true") — repo-variable kill switch
  - ENABLE_IG_PUBLISHING env (must equal "1") — workflow_dispatch gate
  - IG /me/media cross-check — aborts if matching caption exists upstream
  - DRY_RUN env (default "true") — logs payload and exits without /media_publish

Slack alerts at >=3 failures per day (deduped via state file).
"""
from __future__ import annotations

import argparse
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
# Per-run heartbeat consumed by the workflow's Slack notification step.
# Overwritten each run; intentionally NOT committed (gitignored).
RUN_STATUS_FILE = os.path.join(LOGS_DIR, "ig_publish_run_status.json")

MNT_OFFSET = timedelta(hours=8)
FIRST_POST_HOUR_MNT = 8
LAST_POST_HOUR_MNT = 17
# Phase 3D.1: OOW guard tolerates MNT 18-19 so :15/:30 retry cron fires that
# drift past slot 9's hour still publish. Hours 18-19 clamp to idx 9.
WINDOW_END_HOUR_MNT = 19

SLACK_FAILURE_THRESHOLD = 3
SCHEMA_VERSION = 1
HEAD_TIMEOUT_SECONDS = 10
SLACK_TIMEOUT_SECONDS = 10

IG_API_VERSION = "v22.0"
IG_API_TIMEOUT_SECONDS = 10
CROSS_CHECK_PREFIX_LEN = 80
CROSS_CHECK_LIMIT = 25


def _log(msg: str) -> None:
    print(f"[ig_runner] {msg}", file=sys.stderr)


def _now_mnt() -> datetime:
    return datetime.now(timezone.utc) + MNT_OFFSET


def _resolve_post_index(now_mnt: datetime) -> int | None:
    hour = now_mnt.hour
    if hour < FIRST_POST_HOUR_MNT or hour > WINDOW_END_HOUR_MNT:
        return None
    return min(hour - FIRST_POST_HOUR_MNT, LAST_POST_HOUR_MNT - FIRST_POST_HOUR_MNT)


def _resolve_override_idx(cli_idx: int | None) -> int | None:
    """Operator override for post selection (Phase 3B.2 acceleration).

    Precedence: CLI flag --idx wins over the FORCE_IDX env var. Empty or
    unset env var means no override and hour-based logic is used. A non-empty
    env var that fails int() raises ValueError so a config typo surfaces as
    an explicit failure rather than silently falling through to hour logic.
    """
    if cli_idx is not None:
        return cli_idx
    raw = os.environ.get("FORCE_IDX", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"FORCE_IDX env var is not an integer: {raw!r}") from e


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
    """IG_PUBLISH_ENABLED repo-variable kill switch. Default-disabled.

    Must equal "true" (case-insensitive) to allow publishing. Any other value
    — "false", absent, empty — engages the kill switch. Default-disabled
    polarity means an accidentally-deleted variable also blocks the runner.

    Returns (engaged, reason). When engaged, runner exits 0 immediately.
    """
    val = os.environ.get("IG_PUBLISH_ENABLED", "").strip().lower()
    if val == "true":
        return False, ""
    if not val:
        return True, "IG_PUBLISH_ENABLED not set"
    return True, f'IG_PUBLISH_ENABLED="{val}"'


def _is_dry_run() -> bool:
    """DRY_RUN gate. Default 'true' (safe). Set DRY_RUN=false to actually publish."""
    return os.environ.get("DRY_RUN", "true").lower() != "false"


def _check_ig_already_posted(caption: str) -> tuple[bool, str | None]:
    """Cross-check IG Graph API for an upstream post matching this caption.

    Defense-in-depth against duplicates: the local state file may say "not
    yet" while IG already has the post (state-file commit-back failed,
    manual repost, concurrent run, etc.). Match on caption prefix.

    Returns (already_posted, ig_media_id_or_None). On API failure returns
    (False, None) and logs a warning — the cross-check is best-effort and
    must not brick the runner if /me/media is unreachable.
    """
    ig_user_id = os.environ.get("IG_USER_ID")
    access_token = os.environ.get("FB_ACCESS_TOKEN")
    if not ig_user_id or not access_token:
        _log("⚠ IG_USER_ID / FB_ACCESS_TOKEN not set — skipping cross-check")
        return False, None
    url = f"https://graph.facebook.com/{IG_API_VERSION}/{ig_user_id}/media"
    params = {
        "fields": "id,caption,timestamp",
        "access_token": access_token,
        "limit": CROSS_CHECK_LIMIT,
    }
    try:
        resp = requests.get(url, params=params, timeout=IG_API_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        _log(f"⚠ IG /media cross-check network error: {e} — proceeding")
        return False, None
    if resp.status_code != 200:
        _log(f"⚠ IG /media cross-check status {resp.status_code} — proceeding")
        return False, None
    prefix = caption[:CROSS_CHECK_PREFIX_LEN].strip()
    if not prefix:
        return False, None
    for item in resp.json().get("data", []):
        item_caption = (item.get("caption") or "").strip()
        if item_caption.startswith(prefix):
            return True, item.get("id")
    return False, None


def _log_dry_run_payload(image_url: str, caption: str, idx: int, date_str: str) -> None:
    ig_user_id = os.environ.get("IG_USER_ID", "<unset>")
    _log("=== DRY_RUN: would publish ===")
    _log(f"  destination IG_USER_ID: {ig_user_id}")
    _log(f"  post idx:               {idx}")
    _log(f"  date:                   {date_str}")
    _log(f"  image_url:              {image_url}")
    _log(f"  caption ({len(caption)} chars):")
    for line in caption.splitlines():
        _log(f"    | {line}")
    _log("=== DRY_RUN: skipped /media_publish (set DRY_RUN=false to publish) ===")


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


def _write_run_status(status: dict) -> None:
    """Write the per-run summary read by the workflow's Slack step.

    Always called from main()'s finally block so the file reflects the
    actual exit path (or 'unknown' / 'exception' if no branch updated it).
    Best-effort: a write failure logs a warning but does not raise.
    """
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(RUN_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log(f"⚠ failed to write {RUN_STATUS_FILE}: {e}")


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
    parser = argparse.ArgumentParser(description="IG publisher runner")
    parser.add_argument(
        "--idx",
        type=int,
        default=None,
        help=(
            "Override post index, bypassing hour-based selection. "
            "Empty/unset falls back to FORCE_IDX env var, then hour logic."
        ),
    )
    args = parser.parse_args()
    cli_idx = args.idx

    # status accumulates per-run summary; finally block writes it to
    # RUN_STATUS_FILE so the workflow's Slack step can format a notification.
    # Default exit_path "unknown" → finally still writes a useful record if a
    # branch forgot to set it (would surface as "exit_path=unknown" in Slack).
    status: dict = {
        "exit_path": "unknown",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # Kill switch first — fastest mitigation, runs before any other work.
        engaged, reason = _kill_switch_engaged()
        if engaged:
            _log(f"🛑 kill switch: {reason} — exiting without work")
            status["exit_path"] = "kill_switch"
            status["reason"] = reason
            return 0

        if os.environ.get("ENABLE_IG_PUBLISHING") != "1":
            _log("ENABLE_IG_PUBLISHING != 1 — exiting without publish")
            status["exit_path"] = "enable_off"
            return 0

        now_mnt = _now_mnt()
        date_str = now_mnt.strftime("%Y%m%d")
        status["date_str"] = date_str
        try:
            override_idx = _resolve_override_idx(cli_idx)
        except ValueError as exc:
            _log(f"❌ {exc}")
            status["exit_path"] = "force_idx_invalid"
            status["error"] = str(exc)
            return 1
        if override_idx is not None:
            idx = override_idx
            status["force_idx"] = idx
            _log(f"📌 force_idx override: idx={idx} (hour-based logic skipped)")
        else:
            idx = _resolve_post_index(now_mnt)
            if idx is None:
                _log(f"current MNT hour {now_mnt.hour} outside window — exiting")
                status["exit_path"] = "out_of_window"
                status["mnt_hour"] = now_mnt.hour
                return 0
        state_key = f"{date_str}:{idx}"
        status["post_idx"] = idx
        _log(f"MNT now: {now_mnt.isoformat()} -> post idx {idx} (key={state_key})")

        state = _load_state()
        if state["posts"].get(state_key, {}).get("ok"):
            _log(f"already published {state_key} — skipping")
            status["exit_path"] = "already_published_local"
            status["external_id"] = state["posts"][state_key].get("external_id")
            return 0

        if not os.path.exists(INPUT_FILE):
            _log(f"❌ {INPUT_FILE} not found — translator hasn't run today")
            status["exit_path"] = "input_missing"
            status["error"] = f"{INPUT_FILE} not found"
            return 1
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if idx >= len(posts):
            _log(f"idx {idx} out of range (only {len(posts)} posts) — exiting")
            status["exit_path"] = "idx_out_of_range"
            status["posts_total"] = len(posts)
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
            status["exit_path"] = "image_url_unreachable"
            status["error"] = url_err
            return 1

        caption = adapt_caption_for_ig(post)

        # Defense-in-depth: cross-check IG /me/media for an upstream duplicate
        # before publishing. State file may be stale (commit-back failed, manual
        # repost). If found, record the upstream ID and exit success — re-running
        # the runner will then short-circuit on the local state check above.
        already, existing_id = _check_ig_already_posted(caption)
        if already:
            _log(f"✓ IG cross-check: post already exists upstream (id={existing_id}) — recording and exiting")
            cross_check_ts = datetime.now(timezone.utc).isoformat()
            entry = {
                "post_index": idx,
                "ok": True,
                "external_id": existing_id,
                "attempts": 0,
                "via_cross_check": True,
                "timestamp": cross_check_ts,
            }
            _append_log_entry(date_str, entry, cross_check_ts)
            state["posts"][state_key] = {
                "ok": True,
                "external_id": existing_id,
                "via_cross_check": True,
                "timestamp": cross_check_ts,
            }
            _save_state(state)
            status["exit_path"] = "cross_check_duplicate"
            status["external_id"] = existing_id
            return 0

        # DRY_RUN gate (default true). Logs the would-be payload and exits without
        # calling /media_publish. Does NOT update state — next run re-attempts.
        # Set DRY_RUN=false in the workflow env to actually post (Phase 3B.2).
        if _is_dry_run():
            _log_dry_run_payload(image_url, caption, idx, date_str)
            status["exit_path"] = "dry_run"
            return 0

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
        raise
    finally:
        _write_run_status(status)


if __name__ == "__main__":
    sys.exit(main())
