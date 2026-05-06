# YouTube Live Video Feed — Phase 7.3

**Status:** ✅ Implemented in `youtube_fetcher.py`, `.github/workflows/youtube_update.yml`, `deny_list_videos.json`.
**Shipped:** 2026-05-06.

Every 2 hours the backend snapshots a curated set of YouTube channels into `youtube_data.json`. The frontend (`orangenews-website`) consumes via raw GitHub URL and renders the homepage right-rail "Шууд үзэх" section + the `/video` archive route. Replaces the hardcoded `LiveEvent` placeholder card that previously rendered a static "Powell live press conference".

## Why this doc exists

Three things aren't obvious from reading `youtube_fetcher.py` or the workflow YAML cold:

1. **Why the script needs both RSS and the YouTube Data API.** YouTube RSS does NOT expose video duration. The locked Phase 7.3 decision #3 ("skip clips < 3 min") cannot be applied from RSS alone. Hybrid γ source strategy: `feedparser` for free RSS discovery, then a single `videos.list?part=contentDetails` API call (batched up to 50 IDs per call) for duration enrichment. Net: ~2 quota units per run × 12 runs/day = ~24 units/day, ~0.24% of the free 10K daily allowance. The reservation block estimated ~1,080 units/day under a per-video cost model; reality is per-call, much cheaper.

2. **Why `.gitignore` had to be patched.** The repo's existing `*.json` blanket-ignore with explicit allowlist for the live data files would have silently dropped every YouTube write. `!youtube_data.json` + `!deny_list_videos.json` are required (matches the Phase 7.1 `!archive/` allowlist precedent).

3. **Why some channels don't appear in the surviving feed.** Reuters, WSJ, and Financial Times publish mostly YouTube Shorts (under 3 minutes) that fail the locked >3 min quality filter. The surviving feed skews toward channels that produce longer-form content — typical distribution: Bloomberg Television ~13, CNBC ~12, World Bank Group ~6, WSJ ~1, FT ~1, Reuters ~0. The `videos_filtered_short` counter in the output exposes the drop count for operator visibility. Three remediation paths if balance becomes a concern: per-channel cap, lower duration threshold, or accept current distribution.

## Schema

**`youtube_data.json`** — wrapped envelope written each run:

```json
{
  "fetched_at_utc": "2026-05-06T10:13:11Z",
  "fetched_at_mnt": "2026-05-06T18:13:11+0800",
  "channels_processed": 6,
  "videos_total": 33,
  "videos_filtered_short": 53,
  "videos_filtered_denied": 0,
  "videos_filtered_no_duration": 4,
  "errors": [],
  "elapsed_seconds": 0.96,
  "videos": [
    {
      "id": "abc123",
      "title": "...",
      "description": "...",
      "channel_id": "UCIALMKvObZNtJ6AmdCLP7Lg",
      "channel_title": "Bloomberg Television",
      "published_at": "2026-05-06T05:00:00+00:00",
      "thumbnail_url": "https://i3.ytimg.com/vi/abc123/hqdefault.jpg",
      "duration_seconds": 420,
      "duration_iso": "PT7M",
      "watch_url": "https://www.youtube.com/watch?v=abc123",
      "mongolia_relevant": false
    }
  ]
}
```

- `fetched_at_*` — UTC + MNT (Asia/Ulaanbaatar) timestamps for operator clarity.
- `videos_filtered_*` — three drop counters (short / deny-listed / no-duration). Their sum + `videos_total` should equal the number of stubs from RSS (currently 6 channels × ~15 entries = ~90 typical).
- `videos[]` — already filtered + sorted by `published_at` desc + capped at 50. Frontend consumers don't need to filter further.
- `mongolia_relevant` — bool flag from title+description keyword match (`mongolia`, `монгол`, etc.). Per locked decision #3 OR semantics: this is a boost flag for the UI, NOT an exclusion criterion.

**`deny_list_videos.json`** — manual editorial veto list:

```json
["videoId1", "videoId2"]
```

Plain array of YouTube video IDs (the `v=` part of the watch URL). Default: `[]`. Backend skips matching videos and increments `videos_filtered_denied`. Edit the file + commit; next cron tick respects. No restart needed.

## CLI

```
YOUTUBE_API_KEY=<key> python3 youtube_fetcher.py
```

Required env: `YOUTUBE_API_KEY`. Script `sys.exit`s with a Mongolian error message if missing — fails loud rather than writing partial garbage.

## Workflow integration

`.github/workflows/youtube_update.yml`:

- **Cron:** `0 */2 * * *` (every 2 hours, 24/7). Locked decision #1 cadence.
- **Concurrency:** `cancel-in-progress: true` (prevents overlap if a slow run is still going when the next slot fires).
- **Dependencies:** `requests + feedparser`, installed fresh on the runner per workflow.
- **Commit step:** `if git diff --staged --quiet` skip-empty pattern matches the other cron workflows.
- **Failure path:** includes the Phase 8.1 Track A Slack notification step (gated on `SLACK_WEBHOOK_URL` repo secret — opts in once the founder configures the webhook).

## Frontend integration (read side)

The frontend consumes via raw GitHub URL:

```
https://raw.githubusercontent.com/mctunghai-pixel/orange-news-automation/main/youtube_data.json
```

ISR cadence in `lib/fetch-youtube.ts`: 1800 s (30 min). Over-provisioned vs the 2-hour backend cron, but consistent with the other live-data routes (Orange News + market data + MSE). See `CLAUDE.md` in the website repo for the consumer-side details.

## Channel list

Locked in CLAUDE.md Phase 7.3 block (frontend repo). Six curated channels (UC IDs in `youtube_fetcher.py:CHANNELS`):

| Channel | UC ID |
|---|---|
| Bloomberg Television | `UCIALMKvObZNtJ6AmdCLP7Lg` |
| WSJ | `UCK7tptUDHh-RYDsdxO1-5QQ` |
| Reuters | `UChqUTb7kYRX8-EiaN3XFrSQ` |
| Financial Times | `UCoUxsWakJucWg46KW5RsvPw` |
| CNBC | `UCvJJ_dzjViJCoLf5uKUTwoA` |
| World Bank Group | `UCE9mrcoX-oE-2f1BL-iPPoQ` |

**Bloomberg disambiguation** — the brand has 5+ YouTube channels. Bloomberg Television (above) is the canonical financial-news pick. Bloomberg Originals (`UCUMZ7gohGI9HcU9VNsr2FJQ`, formerly `@business`) is long-form documentaries; Bloomberg Live (`UC7UFcUbAd8oyCBWCogVpJ6g`) is event/lifestyle content like "Summer Fun with Kyle Cooke" — both excluded. Bloomberg News (`UChirEOpgFCupRAk5etXqPaA`) is an optional Phase 7.3.x add-on (~30% non-financial overlap).

**To add or remove a channel:** edit the `CHANNELS` dict at the top of `youtube_fetcher.py`, commit, push. The frontend filter UI in `/video` derives the chip list from data (not a hardcoded list), so the change naturally reflects in the UI on the next cron tick.

## Migration policy

Fresh start from 2026-05-06. No historical video archive — RSS only exposes ~15 most-recent entries per channel, so we never had access to deeper history at first run.
