"""Threads publisher — 2-step Graph API flow (mirrors Instagram architecture).

Threads Graph API v1.0:
  1. POST /{THREADS_USER_ID}/threads        -> returns creation_id (container)
  2. GET  /{creation_id}?fields=status      -> poll until FINISHED, <=60s
  3. POST /{THREADS_USER_ID}/threads_publish -> returns Threads media_id

Auth:
  - Long-lived access token (60 days, refreshable). Separate from FB/IG token
    because Threads is a distinct Meta product with its own permissions.
  - Get one via: developers.facebook.com → Threads API → OAuth flow.

Image:
  - Threads API does NOT accept binary uploads. image_url must be publicly
    reachable. We use the same media-public branch hosted on
    raw.githubusercontent.com (same as ig_runner.py).
"""
from __future__ import annotations

import os
import sys
import time

import requests

from publishers.base import Publisher, PublishResult

GRAPH_API_VERSION = "v1.0"
BASE_URL = f"https://graph.threads.net/{GRAPH_API_VERSION}"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 4, 8]
POLL_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2

POST_TIMEOUT_SECONDS = 30
GET_TIMEOUT_SECONDS = 15

# Threads error code categories (mirrors IG mapping; subject to API drift)
_TRANSIENT_CODES = {1, 2, 4, 17, 32}
_PERMANENT_CODES = {100, 190, 200, 803}


class _TransientError(Exception):
    pass


class _PermanentError(Exception):
    pass


def _log(msg: str) -> None:
    print(f"[threads] {msg}", file=sys.stderr)


class ThreadsPublisher(Publisher):
    """Publish a single image+text post to Threads.

    Two-step container flow identical in shape to InstagramPublisher.
    """

    def __init__(self) -> None:
        token = os.environ.get("THREADS_ACCESS_TOKEN")
        user_id = os.environ.get("THREADS_USER_ID")
        if not token:
            raise RuntimeError("THREADS_ACCESS_TOKEN env var not set")
        if not user_id:
            raise RuntimeError("THREADS_USER_ID env var not set")
        self._token = token
        self._user_id = user_id

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

    def publish_text_only(self, text: str) -> PublishResult:
        """Optional path: text-only post (no image). Useful for short alerts."""
        try:
            # Step 1: create text container
            url = f"{BASE_URL}/{self._user_id}/threads"
            data = {
                "media_type": "TEXT",
                "text": text,
                "access_token": self._token,
            }
            resp = requests.post(url, data=data, timeout=POST_TIMEOUT_SECONDS)
            result = self._handle_response(resp, "create_text_container")
            creation_id = result.get("id")
            if not creation_id:
                raise _PermanentError(f"missing id: {result}")
            # Text container is immediately FINISHED — no poll required
            media_id = self._publish_container(creation_id)
            return PublishResult(ok=True, external_id=media_id, attempts=1)
        except (_TransientError, _PermanentError) as e:
            return PublishResult(ok=False, error=str(e), attempts=1)

    # ------------------------------------------------------------------------
    # Internal — Graph API calls
    # ------------------------------------------------------------------------
    def _create_container(self, image_url: str, caption: str) -> str:
        url = f"{BASE_URL}/{self._user_id}/threads"
        data = {
            "media_type": "IMAGE",
            "image_url": image_url,
            "text": caption,
            "access_token": self._token,
        }
        try:
            resp = requests.post(url, data=data, timeout=POST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise _TransientError(f"create_container network: {e}")
        result = self._handle_response(resp, "create_container")
        creation_id = result.get("id")
        if not creation_id:
            raise _PermanentError(f"create_container: missing 'id': {result}")
        return creation_id

    def _wait_for_container(self, creation_id: str) -> None:
        url = f"{BASE_URL}/{creation_id}"
        params = {"fields": "status", "access_token": self._token}
        deadline = time.time() + POLL_TIMEOUT_SECONDS
        last_status = None
        while time.time() < deadline:
            try:
                resp = requests.get(url, params=params, timeout=GET_TIMEOUT_SECONDS)
            except requests.RequestException as e:
                raise _TransientError(f"poll network: {e}")
            data = self._handle_response(resp, "poll_container")
            status = (data.get("status") or "").upper()
            last_status = status
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise _PermanentError(f"container processing failed: {data}")
            if status == "EXPIRED":
                raise _PermanentError(f"container expired: {data}")
            time.sleep(POLL_INTERVAL_SECONDS)
        raise _TransientError(
            f"container poll timeout after {POLL_TIMEOUT_SECONDS}s "
            f"(last status: {last_status})"
        )

    def _publish_container(self, creation_id: str) -> str:
        url = f"{BASE_URL}/{self._user_id}/threads_publish"
        data = {"creation_id": creation_id, "access_token": self._token}
        try:
            resp = requests.post(url, data=data, timeout=POST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise _TransientError(f"publish network: {e}")
        result = self._handle_response(resp, "publish_container")
        media_id = result.get("id")
        if not media_id:
            raise _PermanentError(f"publish: missing 'id': {result}")
        return media_id

    @staticmethod
    def _handle_response(resp: requests.Response, op: str) -> dict:
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _TransientError(f"{op}: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError:
            raise _TransientError(
                f"{op}: non-JSON (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            code = err.get("code")
            subcode = err.get("error_subcode")
            msg = err.get("message", "")
            full = f"{op}: code={code} subcode={subcode} {msg}"
            if code in _TRANSIENT_CODES:
                raise _TransientError(full)
            raise _PermanentError(full)
        if not resp.ok:
            raise _TransientError(f"{op}: HTTP {resp.status_code}")
        return data


# ---------------------------------------------------------------------------
# Token refresh helper (60-day long-lived → refresh anytime within window)
# ---------------------------------------------------------------------------
def refresh_long_lived_token(current_token: str) -> dict:
    """Refresh a long-lived Threads token.

    Returns dict with {access_token, token_type, expires_in}. Refresh anytime
    inside the 60-day window. Call this monthly from a maintenance workflow.
    """
    url = "https://graph.threads.net/refresh_access_token"
    params = {
        "grant_type": "th_refresh_token",
        "access_token": current_token,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()
