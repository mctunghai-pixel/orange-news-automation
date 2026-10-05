"""
freshness.py — shared "is translated_posts.json from today?" check.

Why: on 2026-08-20 the translator started crashing, translated_posts.json
froze, and downstream publishers (Telegram, archive) kept re-using the
same stale posts for 46 days. File mtime cannot be trusted in CI
(actions/checkout stamps every file with the checkout time), so the
translator now stamps each post with `generated_date` (MNT, YYYY-MM-DD)
and every consumer checks it here.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

MNT_TZ = ZoneInfo("Asia/Ulaanbaatar")


def today_mnt() -> str:
    return datetime.now(MNT_TZ).date().isoformat()


def posts_generated_date(posts):
    """Return the generated_date stamped by the translator, or None."""
    if not isinstance(posts, list) or not posts:
        return None
    return posts[0].get("generated_date")


def posts_are_fresh(posts, today=None) -> bool:
    return posts_generated_date(posts) == (today or today_mnt())
