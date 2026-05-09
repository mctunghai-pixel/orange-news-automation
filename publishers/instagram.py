"""Instagram publisher — 2-step Graph API flow with retry and JSON logging.

Flow:
  1. POST /{IG_USER_ID}/media        -> returns creation_id (container)
  2. GET  /{creation_id}?fields=status_code (poll until FINISHED, <=60s)
  3. POST /{IG_USER_ID}/media_publish -> returns IG media_id

The same Meta token (FB_ACCESS_TOKEN) authorizes both FB Page and IG
Business operations because IG Business is linked to the FB Page.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

from publishers.base import Publisher, PublishResult

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 4, 8]
POLL_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2

POST_TIMEOUT_SECONDS = 30
GET_TIMEOUT_SECONDS = 15

_TRANSIENT_GRAPH_CODES = {1, 2, 4, 17, 32}
_PERMANENT_GRAPH_CODES = {100, 190, 200, 803}


class _TransientError(Exception):
    pass


class _PermanentError(Exception):
    pass


def _log(msg: str) -> None:
    print(f"[instagram] {msg}", file=sys.stderr)


class InstagramPublisher(Publisher):
    def __init__(self) -> None:
        token = os.environ.get("FB_ACCESS_TOKEN")
        ig_user_id = os.environ.get("IG_USER_ID")
        if not token:
            raise RuntimeError("FB_ACCESS_TOKEN env var not set")
        if not ig_user_id:
            raise RuntimeError("IG_USER_ID env var not set")
        self._token = token
        self._ig_user_id = ig_user_id

    def publish(self, image_url: str, caption: str) -> PublishResult:
        last_error: str | None = None
        for attempt_num in range(1, MAX_ATTEMPTS + 1):
            try:
                creation_id = self._create_container(image_url, caption)
                self._wait_for_container(creation_id)
                media_id = self._publish_container(creation_id)
                return PublishResult(
                    ok=True,
                    external_id=media_id,
                    attempts=attempt_num,
                )
            except _PermanentError as e:
                _log(f"permanent error (attempt {attempt_num}): {e}")
                return PublishResult(ok=False, error=str(e), attempts=attempt_num)
            except _TransientError as e:
                last_error = str(e)
                _log(f"transient error (attempt {attempt_num}/{MAX_ATTEMPTS}): {e}")
                if attempt_num < MAX_ATTEMPTS:
                    time.sleep(BACKOFF_SECONDS[attempt_num - 1])
        return PublishResult(
            ok=False,
            error=f"max attempts exhausted: {last_error}",
            attempts=MAX_ATTEMPTS,
        )

    def _create_container(self, image_url: str, caption: str) -> str:
        url = f"{BASE_URL}/{self._ig_user_id}/media"
        data = {
            "image_url": image_url,
            "caption": caption,
            "access_token": self._token,
        }
        try:
            resp = requests.post(url, data=data, timeout=POST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise _TransientError(f"create_container network error: {e}")
        result = self._handle_response(resp, "create_container")
        creation_id = result.get("id")
        if not creation_id:
            raise _PermanentError(f"create_container: missing 'id' in response: {result}")
        return creation_id

    def _wait_for_container(self, creation_id: str) -> None:
        url = f"{BASE_URL}/{creation_id}"
        params = {"fields": "status_code", "access_token": self._token}
        deadline = time.time() + POLL_TIMEOUT_SECONDS
        last_status = None
        while time.time() < deadline:
            try:
                resp = requests.get(url, params=params, timeout=GET_TIMEOUT_SECONDS)
            except requests.RequestException as e:
                raise _TransientError(f"poll_container network error: {e}")
            data = self._handle_response(resp, "poll_container")
            status = data.get("status_code")
            last_status = status
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise _PermanentError(f"container processing failed: {data}")
            time.sleep(POLL_INTERVAL_SECONDS)
        raise _TransientError(
            f"container poll timeout after {POLL_TIMEOUT_SECONDS}s "
            f"(last status: {last_status})"
        )

    def _publish_container(self, creation_id: str) -> str:
        url = f"{BASE_URL}/{self._ig_user_id}/media_publish"
        data = {"creation_id": creation_id, "access_token": self._token}
        try:
            resp = requests.post(url, data=data, timeout=POST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise _TransientError(f"publish_container network error: {e}")
        result = self._handle_response(resp, "publish_container")
        media_id = result.get("id")
        if not media_id:
            raise _PermanentError(f"publish_container: missing 'id' in response: {result}")
        return media_id

    @staticmethod
    def _handle_response(resp: requests.Response, op: str) -> dict:
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _TransientError(f"{op}: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError:
            raise _TransientError(
                f"{op}: non-JSON response (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            code = err.get("code")
            subcode = err.get("error_subcode")
            msg = err.get("message", "")
            full = f"{op}: code={code} subcode={subcode} {msg}"
            if code in _TRANSIENT_GRAPH_CODES:
                raise _TransientError(full)
            raise _PermanentError(full)
        if not resp.ok:
            raise _TransientError(f"{op}: HTTP {resp.status_code}")
        return data


def write_ig_publish_log(
    entries: list[dict],
    date_str: str,
    started_at: str,
    finished_at: str,
    *,
    logs_dir: str = "logs",
) -> str:
    """Write logs/ig_publish_log_YYYYMMDD.json. Returns the file path.

    Each entry should have: post_index, ok, external_id, attempts, error,
    timestamp.
    """
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, f"ig_publish_log_{date_str}.json")

    ok_count = sum(1 for e in entries if e.get("ok"))
    payload = {
        "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
        "started_at": started_at,
        "finished_at": finished_at,
        "results": entries,
        "summary": {
            "total": len(entries),
            "ok": ok_count,
            "failed": len(entries) - ok_count,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return path
