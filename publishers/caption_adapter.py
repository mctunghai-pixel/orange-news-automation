"""IG-specific caption adapter — independent of fb_poster.format_post.

IG vs FB caption differences:
  - URLs are not clickable in IG captions: strip "Эх сурвалж:" lines and
    the FB-style footer link block.
  - IG allows up to 30 hashtags; over-30 hides them all.
  - Hard limit: 2200 chars per caption.
  - Feed preview shows ~125 chars before "...more": keep badge+headline first.

This module reads only the post dict's primitive fields (badge, headline,
body_only/post_text, hashtags). It deliberately does NOT import or call
fb_poster.format_post — coupling would risk breaking the FB pipeline when
IG-specific stripping rules evolve.
"""
from __future__ import annotations

import re

CAPTION_LIMIT = 2200
HASHTAG_LIMIT = 30
TRUNCATION_MARKER = "…"

STANDARD_HASHTAGS = [
    "#orangenews",
    "#санхүү",
    "#эдийнзасаг",
    "#зах_зээл",
    "#mongolia",
]

_SOURCE_LINE_RE = re.compile(r"^\s*Эх\s+сурвалж\s*:.*$", re.MULTILINE)
_FOOTER_LINK_RE = re.compile(r"^\s*[🌐📘📷🧵].*$", re.MULTILINE)
_URL_LINE_RE = re.compile(r"^.*(?:orangenews\.mn|https?://\S+).*$", re.MULTILINE)
_DIVIDER_RE = re.compile(r"^━+\s*$", re.MULTILINE)
_JUNK_PATTERNS = [
    re.compile(r"Та үүнийг юу гэж бодож байна\?.*$", re.MULTILINE | re.DOTALL),
    re.compile(r"Сэтгэгдэлээ хуваалцаарай.*$", re.MULTILINE | re.DOTALL),
    re.compile(r"^\s*👇.*$", re.MULTILINE),
]
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _clean_body(body: str) -> str:
    body = _SOURCE_LINE_RE.sub("", body)
    body = _FOOTER_LINK_RE.sub("", body)
    body = _URL_LINE_RE.sub("", body)
    body = _DIVIDER_RE.sub("", body)
    for pat in _JUNK_PATTERNS:
        body = pat.sub("", body)
    body = _MULTI_BLANK_RE.sub("\n\n", body)
    return body.strip()


def _build_hashtags(post_hashtags) -> str:
    if isinstance(post_hashtags, str):
        post_hashtags = post_hashtags.split()
    elif post_hashtags is None:
        post_hashtags = []

    seen: set[str] = set()
    merged: list[str] = []
    for tag in list(STANDARD_HASHTAGS) + list(post_hashtags):
        tag = (tag or "").strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(tag)

    return " ".join(merged[:HASHTAG_LIMIT])


def adapt_caption_for_ig(post: dict) -> str:
    badge = (post.get("badge") or "").strip()
    headline = (post.get("headline") or "").strip()
    raw_body = post.get("body_only") or post.get("post_text") or ""
    body = _clean_body(raw_body)
    hashtag_line = _build_hashtags(post.get("hashtags"))

    if badge and body.startswith(badge):
        body = body[len(badge):].lstrip("\n").strip()
    if headline and body.startswith(headline):
        body = body[len(headline):].lstrip("\n").strip()

    sections = [s for s in (badge, headline, body, hashtag_line) if s]
    caption = "\n\n".join(sections)

    if len(caption) <= CAPTION_LIMIT:
        return caption

    fixed_parts = [s for s in (badge, headline, hashtag_line) if s]
    fixed_overhead = len("\n\n".join(fixed_parts))
    separators_for_body = (len("\n\n") if (badge or headline) else 0) + (
        len("\n\n") if hashtag_line else 0
    )
    body_budget = CAPTION_LIMIT - fixed_overhead - separators_for_body - len(TRUNCATION_MARKER)

    if body_budget <= 0:
        return caption[:CAPTION_LIMIT]

    truncated_body = body[:body_budget].rstrip() + TRUNCATION_MARKER
    sections = [s for s in (badge, headline, truncated_body, hashtag_line) if s]
    return "\n\n".join(sections)
