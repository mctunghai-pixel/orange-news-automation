"""mse_data_fetcher.py

Fetches Mongolian Stock Exchange data via Next.js Server Actions on mse.mn.
Mirrors the market_data_fetcher.py pattern: single file, requests-based,
JSON output to repo root for downstream consumption (orangenews-website).

Endpoint mechanics:
  POST https://mse.mn/
  next-action: <build-hash>   <-- rotates on mse.mn redeploy (~1-3 mo)
  accept: text/x-component
  Body: [{"url": "<dataset>", "parameter": "...", "config": {"hasToken": false}}]
  Response: RSC stream — parse line "1:[...]" as JSON.

Action-ID rotation strategy:
  1. Try HARDCODED_ACTION_ID
  2. On 4xx, rediscover_action_id() from JS bundles, retry once
  3. Log to errors[] in output JSON
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

# =============================================================================
# CONFIG
# =============================================================================

# Rotates on mse.mn redeploy. Auto-rediscovers via rediscover_action_id() on 4xx.
HARDCODED_ACTION_ID = "6d867ebd99fb6edef2f9537b22668cd0c00a71c2"

ENDPOINT = "https://mse.mn/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/17.0 Safari/537.36 OrangeNewsBot/1.0"
)
ROUTER_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D"
    "%2C%22%2F%22%2C%22refresh%22%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
)
HTTP_TIMEOUT = 15
OUTPUT_FILE = "mse_data.json"

# =============================================================================
# HELPER PARSERS
# =============================================================================

_DIFFPER_RE = re.compile(r"\s*([+-]?[\d.]+)\s*\(\s*([+-]?[\d.]+)%\s*\)\s*")

def parse_comma_float(s):
    """'262,371,826.00' -> 262371826.0"""
    if s is None:
        return 0.0
    return float(str(s).replace(",", "").strip() or 0)

def parse_diffper(s):
    """'+57.00 (+20.36%)' -> (57.0, 20.36)"""
    if not s:
        return 0.0, 0.0
    m = _DIFFPER_RE.match(str(s))
    if not m:
        return 0.0, 0.0
    return float(m.group(1)), float(m.group(2))

def normalize_starttime(s):
    """'2026-05-01 12:00:00' -> '2026-05-01T12:00:00'"""
    if not s:
        return ""
    return str(s).replace(" ", "T", 1)

def derive_direction(change_pct):
    if change_pct is None:
        return "flat"
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "flat"

def to_float(x):
    """Coerce int/float/str-numeric to float; None/'' -> 0.0"""
    if x is None or x == "":
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0

# =============================================================================
# RSC PARSE
# =============================================================================

class StaleActionError(Exception):
    pass

def parse_rsc(body):
    """Extract the first JSON-decodable line of an RSC stream.
    NOTE: split on '\\n' only — splitlines() recognizes Unicode NEL (U+0085),
    which appears as the second byte of UTF-8 'х' (Cyrillic) and would
    fragment Mongolian payloads."""
    for line in body.split("\n"):
        if not line:
            continue
        idx_sep = line.find(":")
        if idx_sep <= 0:
            continue
        idx, payload = line[:idx_sep], line[idx_sep + 1:]
        if idx == "0":
            continue
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            continue
    return None

# =============================================================================
# CORE FETCH
# =============================================================================

def _build_headers(action_id):
    return {
        "next-action": action_id,
        "accept": "text/x-component",
        "content-type": "text/plain;charset=UTF-8",
        "next-router-state-tree": ROUTER_TREE,
        "user-agent": USER_AGENT,
        "referer": "https://mse.mn/",
        "origin": "https://mse.mn",
    }

def fetch_dataset(name, parameter, action_id):
    """Returns parsed JSON list or raises StaleActionError on 4xx."""
    body = [{"url": name, "parameter": parameter, "config": {"hasToken": False}}]
    r = requests.post(
        ENDPOINT,
        headers=_build_headers(action_id),
        data=json.dumps(body),
        timeout=HTTP_TIMEOUT,
    )
    if 400 <= r.status_code < 500:
        raise StaleActionError(f"{name}: HTTP {r.status_code}")
    r.raise_for_status()
    # Stale action ID surfaces as 200 + text/html (Next.js falls back to
    # serving the homepage shell). The valid RSC reply uses text/x-component.
    content_type = r.headers.get("content-type", "")
    if "x-component" not in content_type:
        raise StaleActionError(
            f"{name}: HTTP 200 but content-type={content_type!r} (action ID likely stale)"
        )
    text = r.content.decode("utf-8")
    parsed = parse_rsc(text)
    if parsed is None:
        raise ValueError(f"{name}: could not parse RSC body")
    return parsed

_ACTION_HEX_RE = re.compile(r'"([0-9a-f]{40})"')
# Captures the primary Server Action — assigned to a variable in minified code:
#   var o=(0,r.$)("6d867ebd99fb6edef2f9537b22668cd0c00a71c2")
# Other actions in the same chunk are unbound calls and lack `var X=`.
_VAR_ASSIGN_ACTION_RE = re.compile(
    r'\bvar\s+\w+\s*=\s*\([^)]+\)\(\s*"([0-9a-f]{40})"\s*\)'
)

def _candidate_works(action_id):
    """Probe with a known dataset; require list[dict] with 'symbol' key."""
    body = json.dumps([{"url": "marquee_data", "config": {"hasToken": False}}])
    try:
        r = requests.post(
            ENDPOINT,
            headers=_build_headers(action_id),
            data=body,
            timeout=10,
        )
    except requests.RequestException:
        return False
    if r.status_code != 200:
        return False
    if "x-component" not in r.headers.get("content-type", ""):
        return False
    try:
        parsed = parse_rsc(r.content.decode("utf-8"))
    except Exception:
        return False
    return (
        isinstance(parsed, list)
        and len(parsed) > 0
        and isinstance(parsed[0], dict)
        and "symbol" in parsed[0]
    )

def rediscover_action_id():
    """Re-extract the current Server Action ID from mse.mn JS bundles.

    Strategy: prefer tokens that appear as `var X=(...)("HEX")` (assigned
    to a variable — the primary action handler is always so bound). Fall
    back to probing every 40-hex token until one returns the marquee_data
    shape. The candidate set is small (~9 tokens at time of writing).
    """
    homepage = requests.get(
        ENDPOINT, headers={"user-agent": USER_AGENT}, timeout=HTTP_TIMEOUT
    ).text
    chunks = re.findall(r'src="(/_next/static/chunks/[^"]+)"', homepage)
    if not chunks:
        raise StaleActionError("rediscover: no chunks in homepage")

    var_bound = []
    all_tokens = []
    seen = set()
    for path in chunks:
        try:
            js = requests.get(
                f"https://mse.mn{path}",
                headers={"user-agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            ).text
        except requests.RequestException:
            continue
        for tok in _VAR_ASSIGN_ACTION_RE.findall(js):
            if tok not in seen:
                var_bound.append(tok); seen.add(tok)
        for tok in _ACTION_HEX_RE.findall(js):
            if tok not in seen:
                all_tokens.append(tok); seen.add(tok)

    candidates = var_bound + all_tokens
    if not candidates:
        raise StaleActionError("rediscover: no 40-hex tokens in any chunk")

    for action_id in candidates:
        if _candidate_works(action_id):
            return action_id

    raise StaleActionError(
        f"rediscover: tried {len(candidates)} candidate(s), none returned valid marquee_data"
    )

# =============================================================================
# TRANSFORMS — raw upstream shape -> canonical schema
# =============================================================================

def transform_marquee(item):
    pct = to_float(item.get("percent"))
    return {
        "symbol": item.get("symbol", ""),
        "price": to_float(item.get("value")),
        "change_pct": pct,
        "change_abs": to_float(item.get("Changes")),
        "direction": derive_direction(pct),
    }

def transform_stock_amount(item):
    pct = to_float(item.get("changePercentage"))
    return {
        "symbol": item.get("legalDocument", ""),
        "name": item.get("companyName", ""),
        "code": item.get("code"),
        "logo_url": item.get("avatar", ""),
        "amount_mnt": parse_comma_float(item.get("amount")),
        "change_pct": pct,
        "change_abs": to_float(item.get("changePrice")),
        "direction": derive_direction(pct),
    }

def transform_stock_movers(item):
    """Used for both stock_up (gainers) and stock_down (losers).
    Same shape; differs from stock_amount in carrying `price` not `amount`."""
    pct = to_float(item.get("changePercentage"))
    return {
        "symbol": item.get("legalDocument", ""),
        "name": item.get("companyName", ""),
        "code": item.get("code"),
        "logo_url": item.get("avatar", ""),
        "price": to_float(item.get("price")),
        "change_pct": pct,
        "change_abs": to_float(item.get("changePrice")),
        "direction": derive_direction(pct),
    }

def transform_directory(item):
    """For mseAList / mseBList / top20List — listing only, no prices."""
    return {
        "row": item.get("rowNumber"),
        "symbol": item.get("symbol", ""),
        "name": item.get("name", ""),
        "code": item.get("code"),
    }

def transform_comex(item):
    change_abs, change_pct = parse_diffper(item.get("diffPer"))
    return {
        "id": item.get("id"),
        "main_type": item.get("mainType", ""),
        "category": item.get("catName", ""),
        "seller": item.get("sellerName", ""),
        "started_at": normalize_starttime(item.get("starttime")),
        "min_price": to_float(item.get("min_price")),
        "price": to_float(item.get("price")),
        "currency": item.get("currency", ""),
        "change_abs": change_abs,
        "change_pct": change_pct,
        "direction": derive_direction(change_pct),
    }

# =============================================================================
# MVP DATASET REGISTRY
# =============================================================================

# (upstream_name, parameter, output_key, transform_fn)
MVP_DATASETS = [
    ("marquee_data", "",                              "marquee",       transform_marquee),
    ("stock_amount", "?lang=mn&segments=[1,2,3]",     "stock_amount",  transform_stock_amount),
    ("stock_up",     "?lang=mn&segments=[1,2,3]",     "stock_up",      transform_stock_movers),
    ("stock_down",   "?lang=mn&segments=[1,2,3]",     "stock_down",    transform_stock_movers),
    ("comexTrade",   "?product_type=0&lang=mn&limit=5", "comex_trade", transform_comex),
    ("mseAList",     "?lang=mn",                      "mseA_list",     transform_directory),
    ("mseBList",     "?lang=mn",                      "mseB_list",     transform_directory),
    ("top20List",    "?lang=mn",                      "top20_list",    transform_directory),
]

# =============================================================================
# MAIN
# =============================================================================

def main():
    started = datetime.now(timezone.utc)
    result = {
        "fetched_at_utc": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fetched_at_mnt": started.astimezone(ZoneInfo("Asia/Ulaanbaatar"))
                                .isoformat(timespec="seconds"),
        "action_id_used": HARDCODED_ACTION_ID,
        "rediscovered": False,
        "errors": [],
    }

    action_id = HARDCODED_ACTION_ID

    for upstream, parameter, out_key, transform in MVP_DATASETS:
        print(f"  fetching {upstream:14} -> {out_key}")
        try:
            raw_items = fetch_dataset(upstream, parameter, action_id)
        except StaleActionError as e:
            print(f"    stale action_id ({e}), rediscovering...")
            try:
                new_id = rediscover_action_id()
            except Exception as re_err:
                msg = f"{out_key}: rediscover failed: {re_err}"
                print(f"    {msg}")
                result["errors"].append(msg)
                result[out_key] = []
                continue
            action_id = new_id
            result["action_id_used"] = new_id
            result["rediscovered"] = True
            result["errors"].append(
                f"action ID rotated: hardcoded {HARDCODED_ACTION_ID} stale; "
                f"rediscovered {new_id} on {upstream}"
            )
            try:
                raw_items = fetch_dataset(upstream, parameter, action_id)
            except Exception as retry_err:
                msg = f"{out_key}: retry after rediscover failed: {retry_err}"
                print(f"    {msg}")
                result["errors"].append(msg)
                result[out_key] = []
                continue
        except Exception as e:
            msg = f"{out_key}: fetch failed: {type(e).__name__}: {e}"
            print(f"    {msg}")
            result["errors"].append(msg)
            result[out_key] = []
            continue

        if not isinstance(raw_items, list):
            msg = f"{out_key}: expected list, got {type(raw_items).__name__}"
            print(f"    {msg}")
            result["errors"].append(msg)
            result[out_key] = []
            continue

        try:
            result[out_key] = [transform(item) for item in raw_items]
        except Exception as e:
            msg = f"{out_key}: transform failed: {type(e).__name__}: {e}"
            print(f"    {msg}")
            result["errors"].append(msg)
            result[out_key] = []

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    result["elapsed_seconds"] = round(elapsed, 2)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {OUTPUT_FILE} | {os.path.getsize(OUTPUT_FILE)} bytes | {elapsed:.2f}s")
    print(f"Errors: {len(result['errors'])}")
    for err in result["errors"]:
        print(f"  - {err}")

if __name__ == "__main__":
    main()
