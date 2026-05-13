"""
Tests for the preserve-on-failure guard in youtube_fetcher.main().

Run:
    python -m unittest tests.test_youtube_guard -v

Stdlib only — no pytest dependency. Each test monkey-patches the network
boundary (parse_rss_for_channel / enrich_with_durations) and inspects
whether OUTPUT_FILE was rewritten.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

# Make repo root importable when run from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import youtube_fetcher  # noqa: E402


SENTINEL_PAYLOAD = {
    "fetched_at_utc": "2099-01-01T00:00:00Z",
    "fetched_at_mnt": "2099-01-01T08:00:00+0800",
    "channels_processed": 6,
    "videos_total": 1,
    "videos_filtered_short": 0,
    "videos_filtered_denied": 0,
    "videos_filtered_no_duration": 0,
    "errors": [],
    "elapsed_seconds": 0.0,
    "videos": [
        {
            "id": "SENTINEL_ID",
            "title": "SENTINEL — must not be overwritten by all-fail run",
            "description": "",
            "channel_id": "UCSENTINEL",
            "channel_title": "Sentinel",
            "published_at": "2099-01-01T00:00:00+00:00",
            "thumbnail_url": "",
            "watch_url": "https://www.youtube.com/watch?v=SENTINEL_ID",
            "duration_seconds": 600,
            "duration_iso": "PT10M",
            "mongolia_relevant": False,
        }
    ],
}


class GuardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="ytguard_")
        self.output_path = Path(self.tmp) / "youtube_data.json"
        self.deny_path = Path(self.tmp) / "deny_list.txt"
        self.deny_path.write_text("", encoding="utf-8")

        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(SENTINEL_PAYLOAD, f, ensure_ascii=False, indent=2)
        self.pre_mtime = self.output_path.stat().st_mtime_ns
        self.pre_bytes = self.output_path.read_bytes()

        self._cwd = os.getcwd()
        os.chdir(self.tmp)

        # Patch module-level constants so fetcher writes to our tmp dir.
        self._output_patch = patch.object(
            youtube_fetcher, "OUTPUT_FILE", str(self.output_path)
        )
        self._deny_patch = patch.object(
            youtube_fetcher, "DENY_LIST_FILE", str(self.deny_path)
        )
        self._env_patch = patch.dict(
            os.environ, {"YOUTUBE_API_KEY": "test-key-not-used"}
        )
        self._output_patch.start()
        self._deny_patch.start()
        self._env_patch.start()

    def tearDown(self) -> None:
        self._output_patch.stop()
        self._deny_patch.stop()
        self._env_patch.stop()
        os.chdir(self._cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Test 1: all channels fail → file NOT overwritten
    # ------------------------------------------------------------------
    def test_all_channels_fail_preserves_prior_payload(self) -> None:
        def fake_rss(uc_id, channel_title, errors):
            errors.append(
                f"{channel_title}: RSS эвдэрсэн "
                f"(<unknown>:3:11: not well-formed (invalid token))"
            )
            return []

        def fake_enrich(stubs, api_key, errors):
            return {}

        buf = io.StringIO()
        with patch.object(youtube_fetcher, "parse_rss_for_channel", fake_rss), \
             patch.object(youtube_fetcher, "enrich_with_durations", fake_enrich), \
             redirect_stdout(buf):
            youtube_fetcher.main()

        post_mtime = self.output_path.stat().st_mtime_ns
        post_bytes = self.output_path.read_bytes()

        self.assertEqual(
            self.pre_bytes, post_bytes,
            "All-fail run must NOT overwrite youtube_data.json",
        )
        self.assertEqual(
            self.pre_mtime, post_mtime,
            "All-fail run must NOT touch file mtime",
        )

        log = buf.getvalue()
        self.assertIn("Бүх", log, "Cyrillic warning must appear in log")
        self.assertIn("хадгалж байна", log, "Preserve-message must appear")
        self.assertIn("RSS эвдэрсэн", log, "Per-channel error detail must echo")

    # ------------------------------------------------------------------
    # Test 2: partial success → file IS overwritten
    # ------------------------------------------------------------------
    def test_partial_success_overwrites(self) -> None:
        good_stub = {
            "id": "FRESH123abc",
            "title": "Fresh video from the partial-success path",
            "description": "ok",
            "channel_id": "UCFRESH",
            "channel_title": "Fresh",
            "published_at": "2026-05-13T00:00:00+00:00",
            "thumbnail_url": "",
            "watch_url": "https://www.youtube.com/watch?v=FRESH123abc",
        }

        call_count = {"n": 0}

        def fake_rss(uc_id, channel_title, errors):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [dict(good_stub)]
            errors.append(
                f"{channel_title}: RSS эвдэрсэн "
                f"(<unknown>:3:11: not well-formed (invalid token))"
            )
            return []

        def fake_enrich(stubs, api_key, errors):
            return {
                "FRESH123abc": {
                    "duration_seconds": 600,
                    "duration_iso": "PT10M",
                }
            }

        buf = io.StringIO()
        with patch.object(youtube_fetcher, "parse_rss_for_channel", fake_rss), \
             patch.object(youtube_fetcher, "enrich_with_durations", fake_enrich), \
             redirect_stdout(buf):
            youtube_fetcher.main()

        post_bytes = self.output_path.read_bytes()
        self.assertNotEqual(
            self.pre_bytes, post_bytes,
            "Partial-success run MUST overwrite youtube_data.json",
        )

        with self.output_path.open(encoding="utf-8") as f:
            new_payload = json.load(f)
        self.assertGreaterEqual(new_payload["channels_processed"], 1)
        self.assertEqual(new_payload["videos_total"], 1)
        self.assertEqual(new_payload["videos"][0]["id"], "FRESH123abc")

    # ------------------------------------------------------------------
    # Test 3: Cyrillic round-trip — logs and error strings encode safely
    # ------------------------------------------------------------------
    def test_cyrillic_log_encoding(self) -> None:
        def fake_rss(uc_id, channel_title, errors):
            errors.append(f"{channel_title}: RSS эвдэрсэн — тест")
            return []

        def fake_enrich(stubs, api_key, errors):
            return {}

        buf = io.StringIO()
        with patch.object(youtube_fetcher, "parse_rss_for_channel", fake_rss), \
             patch.object(youtube_fetcher, "enrich_with_durations", fake_enrich), \
             redirect_stdout(buf):
            youtube_fetcher.main()

        log = buf.getvalue()
        log.encode("utf-8").decode("utf-8")
        for token in ("Бүх", "сувгийн", "хадгалж", "эвдэрсэн", "тест"):
            self.assertIn(token, log, f"Cyrillic token {token!r} missing from log")


if __name__ == "__main__":
    unittest.main(verbosity=2)
