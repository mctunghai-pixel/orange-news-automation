# MSE data endpoint — Phase 6.2

**Status:** ✅ Implemented in `mse_data_fetcher.py` and `.github/workflows/mse_update.yml`.
**Discovered:** 2026-05-03 (supersedes 2026-05-02 "no public API" verdict, which stopped at `/api/*` 404s and missed the Next.js Server Actions pattern).

mse.mn data is reachable via a direct `POST https://mse.mn/` with a Server Action header. No browser, no auth, no session warmup. Phase 6.2 ships with a `requests`-based fetcher; Playwright is **not** in the production cron path.

## Why this doc exists

Future contributors (or future-Claude) need to understand four things that aren't obvious from reading `mse_data_fetcher.py` cold:

1. **Why `POST /` works at all** (Next.js Server Actions, not REST)
2. **Why the action ID rotates** (and how the auto-rediscovery works)
3. **Why `splitlines()` would corrupt Mongolian text** (the 0x85 NEL gotcha)
4. **What datasets exist beyond the 8-dataset MVP** (for Phase 6.3+ expansion)

## Endpoint mechanics

- **URL:** `POST https://mse.mn/`
- **Required headers:**
  - `next-action: <build-hash>` — currently `6d867ebd99fb6edef2f9537b22668cd0c00a71c2`. Rotates on every mse.mn redeploy (~1–3 month cadence based on typical Next.js sites).
  - `accept: text/x-component`
  - `content-type: text/plain;charset=UTF-8`
  - `next-router-state-tree: %5B%22%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2F%22%2C%22refresh%22%5D%7D%2Cnull%2Cnull%2Ctrue%5D`
- **Body:** `[{"url":"<dataset_name>","parameter":"<query_string>","config":{"hasToken":false}}]`. `parameter` may be omitted on simple datasets like `marquee_data`.
- **Auth:** none. `hasToken: false` is universal across all 28 observed datasets. No cookies, JWT, CSRF, or session.
- **Response:** RSC stream (`text/x-component`). Line `0` is metadata, line `1+` is the JSON payload. See parsing notes below.
- **Latency:** ~300ms per request from a residential connection; ~150ms from a GHA runner.

## Stale action ID detection — NOT 4xx

When the action ID is wrong, **mse.mn returns HTTP 200 with `Content-Type: text/html`** (the homepage shell), NOT a 4xx. Detect via content-type, not status code:

```python
if "x-component" not in r.headers.get("content-type", ""):
    raise StaleActionError(...)
```

This was caught by deliberate fault-injection during Phase 6.2 implementation. A "4xx-only" implementation would silently break on the first action-ID rotation in production — the cron would write a `mse_data.json` with all 8 datasets empty and no clear failure signal.

## Action-ID auto-rediscovery

When stale, `rediscover_action_id()` fetches the homepage, downloads each `/_next/static/chunks/*.js` referenced, and searches for the action ID:

1. **First pass (high-confidence):** Look for `var X=(0,Y.Z)("HEX")` — the assignment-to-variable form. The primary Server Action is always so bound; other actions in the same chunk are unbound calls. At time of writing this matches exactly the right token.
2. **Fallback:** Probe every 40-hex token in the chunks until one returns a valid `marquee_data` shape (`list[dict]` with `"symbol"` key). Bounded by ~9 tokens.

Cost: ~15s rediscovery wall-clock (downloading ~30 chunks). Acceptable since rediscovery only fires when mse.mn redeploys.

The rediscovered ID is logged to `errors[]` in the JSON output for operator visibility:

```
action ID rotated: hardcoded <old> stale; rediscovered <new> on marquee_data
```

If both passes fail, raise `StaleActionError` and the affected dataset writes as `[]` — other datasets continue (cron doesn't abort).

## RSC parsing — the Cyrillic 'х' / NEL gotcha

The response is an RSC stream. Each line is `<index>:<json>`. Naïve parsing:

```python
# WRONG — silently corrupts data
for line in body.splitlines():
    if line.startswith("1:"):
        return json.loads(line[2:])
```

`str.splitlines()` recognizes a wide set of Unicode line terminators including U+0085 (NEL). The Cyrillic letter "х" (lowercase ha, U+0445) is UTF-8 byte sequence `0xD1 0x85`. When `requests.text` decodes the response with the wrong charset (or when Python sees `0x85` as a code point), `splitlines()` fragments the JSON wherever Mongolian text contains "х". Symptom: `json.JSONDecodeError: Unterminated string` mid-payload.

The fix:

```python
# Correct — split on \n only
for line in body.split("\n"):
    if line.startswith("1:"):
        return json.loads(line[2:])
```

Plus force UTF-8 decode at the boundary: `r.content.decode("utf-8")` (don't trust `r.text`, which falls back to latin-1 when no charset header is set).

This gotcha is documented in the fetcher source at `mse_data_fetcher.py` (search for "NEL").

## 28 datasets enumerated — MVP uses 8

The Phase 6.2 MVP fetches 8 of them. The other 20 are documented for Phase 6.3+ scope.

### MVP (8 datasets — all wired in `mse_data_fetcher.py`)

| Output key | Upstream `url` | Param | Items | Purpose |
|---|---|---|---|---|
| `marquee` | `marquee_data` | `(none)` | 61 | Live ticker ribbon — broadest price coverage |
| `stock_amount` | `stock_amount` | `?lang=mn&segments=[1,2,3]` | 10 | Most active by trade amount (MNT volume) |
| `stock_up` | `stock_up` | `?lang=mn&segments=[1,2,3]` | 10 | Top gainers |
| `stock_down` | `stock_down` | `?lang=mn&segments=[1,2,3]` | 10 | Top losers |
| `comex_trade` | `comexTrade` | `?product_type=0&lang=mn&limit=5` | 5 | Most recent mining/commodity trades |
| `mseA_list` | `mseAList` | `?lang=mn` | 25 | A-board company directory (name + ticker) |
| `mseB_list` | `mseBList` | `?lang=mn` | 43 | B-board company directory |
| `top20_list` | `top20List` | `?lang=mn` | 20 | TOP 20 index members |

The directory datasets (`mseA_list`, `mseB_list`, `top20_list`) carry **no prices** — only `rowNumber`, `symbol`, `name`, `code`. Use them as symbol→name lookup tables to enrich `marquee` rows in the UI.

### Available but not in MVP (20 datasets — Phase 6.3+)

- **Index history:** `mseAData` (142KB), `mseBData` (142KB) — daily price series since 2018
- **Market summary:** `index_table` (228B), `market_data` (185B), `top20Data`
- **Bonds:** `stock_up_bond`, `stock_down_bond`, `stock_amount_bond` (each by `type=BD` or `type=IABS`)
- **News & content:** `news`, `home_company_contents`, `home_company_finance_contents`, `home_company_agenda_contents`, `home_slide`
- **Reference:** `companySelectData`, `menuData`

## Schema conversions (MVP)

Per-dataset transforms in `mse_data_fetcher.py` apply these rules:

- `legalDocument` → `symbol` (the field is the ticker, not a legal document)
- `rowNumber` → `row`
- `avatar` → `logo_url` (kept for future logo URLs even if currently empty)
- `amount: "262,371,826.00"` → `amount_mnt: 262371826.0` (parse_comma_float)
- `diffPer: "+57.00 (+20.36%)"` → `change_abs, change_pct` (regex extract)
- `starttime: "2026-05-01 12:00:00"` → `started_at: "2026-05-01T12:00:00"` (ISO normalize)
- `min_price`, `price` (str) → float
- `direction` ∈ `{"up", "down", "flat"}` derived from `change_pct`

Type normalization: `changePercentage` and `changePrice` arrive as `int` for some rows and `float` for others in the same response. The fetcher coerces to `float` at the boundary.

## Output schema (`mse_data.json`)

Top-level fields:
```
fetched_at_utc:  ISO-8601 with "Z"
fetched_at_mnt:  ISO-8601 with +08:00 offset (Asia/Ulaanbaatar)
action_id_used:  the action ID actually used (hardcoded or rediscovered)
rediscovered:    bool — true if rediscovery fired this run
errors:          list[str] — per-dataset failures + rediscovery log
elapsed_seconds: total wall-clock for the run

marquee:         list[{symbol, price, change_pct, change_abs, direction}]
stock_amount:    list[{symbol, name, code, logo_url, amount_mnt, change_pct, change_abs, direction}]
stock_up:        list[{symbol, name, code, logo_url, price, change_pct, change_abs, direction}]
stock_down:      (same shape as stock_up)
comex_trade:     list[{id, main_type, category, seller, started_at, min_price, price, currency, change_abs, change_pct, direction}]
mseA_list:       list[{row, symbol, name, code}]
mseB_list:       (same shape)
top20_list:      (same shape)
```

## Encoding gotcha — `menuData` mojibake

Most datasets return clean UTF-8. The `menuData` payload (not in MVP) returns mojibake — `Ò®Ð½ÑÑ‚` instead of `Үнэт` — the "UTF-8 bytes interpreted as Latin-1 then re-encoded as UTF-8" double-encoding pattern. If a future phase adds `menuData`, fix per-field with `text.encode('latin-1').decode('utf-8')`. The 8 MVP datasets are clean.

## Cron schedule

`.github/workflows/mse_update.yml` runs `0 2,8 * * 1-5` UTC = **10:00 + 16:00 MNT, weekdays only** (MSE doesn't trade weekends). Free tier budget: ~10 runs/week × ~3s = ~1 minute/month — negligible.

## Dead paths (kept here so future contributors don't redo them)

- `/api/*` REST routes → all 404. The SPA does **not** use Next.js API routes; it uses Server Actions instead.
- `api.mse.mn`, `data.mse.mn`, `quotes.mse.mn`, `trading.mse.mn`, `backend.mse.mn`, `ws.mse.mn` → all NXDOMAIN / connection refused.
- Static HTML scraping → SPA shell, ~7–8KB, zero data.
- TradingView MSE coverage → still nonexistent (probed 2026-05-02).
- Bloomberg Terminal → ~$24K/year, out of scope.

## What still needs commercial relationships

Real-time tick data (sub-second updates) and historical intraday OHLCV are not in the Server Action catalog observed. For those, MSE / TDB Securities / Khan Securities outreach still applies. The 28 discovered datasets are end-of-day or near-real-time — sufficient for an *editorial* Bloomberg-Mongolia product, not for HFT.

## ToS posture

mse.mn is Mongolia's public stock exchange. Public market data scraping is industry-standard for financial journalism (Bloomberg, Reuters, FT). Conservative cron (twice-daily, weekdays). Standard `User-Agent` with `OrangeNewsBot/1.0` suffix — no impersonation. Attribution `Эх сурвалж: Монголын хөрөнгийн бирж (mse.mn)` is required on every MSE-derived UI element. If mse.mn requests we stop, we stop and pivot to direct partnership outreach.
