# Article archive — Phase 7.1

**Status:** ✅ Implemented in `archive_writer.py`, `.github/workflows/orange_news.yml` (Phase 3.5), and `.github/workflows/market_watch_live.yml` (Phase 3.5).
**Shipped:** 2026-05-05 (Day 5).

After every pipeline run the backend snapshots `translated_posts.json` into `archive/posts_{YYYY-MM-DD}.json` and upserts `archive/index.json`. The frontend (`orangenews-website`) consumes those raw GitHub URLs to keep yesterday's articles resolvable on `/articles/[slug]` and to feed a 7-day RSS window. Without this the daily pipeline overwrite caused yesterday's articles to vanish from every route.

## Why this doc exists

Three things aren't obvious from reading `archive_writer.py` or the workflow YAMLs cold:

1. **Why `.gitignore` had to be patched.** The repo's existing `*.json` blanket-ignore with explicit allowlist for the three live files (`translated_posts.json`, `market_data.json`, `mse_data.json`) would have silently dropped every archive write — files create locally, never commit, frontend gets 404s on the raw URL. `!archive/` + `!archive/*.json` are required.
2. **Why `archive_writer` skips when mtime mismatches today.** If Phase 2 (translator) failed, `translated_posts.json` retains yesterday's content. Without the mtime guard, archive_writer would happily snapshot yesterday's content as today's archive — corrupt history that the next successful run wouldn't catch (it'd just overwrite today's wrong file with today's right file, leaving any day where translator failed permanently misattributed).
3. **Why both workflows write archive (and how to read the `source` field).** `orange_news.yml` (~06:00 MNT) and `market_watch_live.yml` (~07:00 MNT) both run the translator and both write today's archive. MW writes last, so the typical `source` field reads `market_watch_live.yml`. If `orange_news.yml` ran but MW failed, the day's archive will say `orange_news.yml`. The field is for operator forensics, not for selecting "the canonical batch" — both workflows produce equivalent 10-post snapshots from the same translator invocation.

## Schema

**`archive/posts_{YYYY-MM-DD}.json`** — wrapped per-day file:

```json
{
  "date": "2026-05-05",
  "generated_at": "2026-05-05T03:13:08Z",
  "source": "orange_news.yml",
  "posts": [...]
}
```

- `date` — MNT editorial day, matches the filename. Determined via `ZoneInfo("Asia/Ulaanbaatar")` so the archive boundary follows the editorial cycle, not UTC.
- `generated_at` — UTC ISO 8601, the moment archive_writer wrote the file.
- `source` — workflow filename (`orange_news.yml` / `market_watch_live.yml`) or `manual` for operator-initiated runs.
- `posts` — array of full `OrangeNewsPost` objects, identical shape to `translated_posts.json` (10 entries: 1 market_watch + 9 news). Frontend filters by `type === "news"` for article surfaces; market_watch is routed elsewhere.

**`archive/index.json`** — manifest:

```json
[
  {"date": "2026-05-05", "count": 10},
  {"date": "2026-05-04", "count": 10}
]
```

Sorted desc by date. `count` includes both news and market_watch posts; the frontend filters during consumption.

## CLI

```
python3 archive_writer.py --source <workflow_filename>   # required: 'orange_news.yml', 'market_watch_live.yml', or 'manual'
                          [--date YYYY-MM-DD]            # optional: override today; bypasses the mtime guard
```

Idempotent: re-running for the same date overwrites the per-day file and upserts the index entry. The `source` field reflects the most recent writer.

## Workflow integration

Both daily workflows have a Phase 3.5 step inserted between Phase 3 (publish) and Phase 4 (commit):

```yaml
- name: Phase 3.5 - Archive snapshot
  if: always()
  run: |
    python3 archive_writer.py --source <workflow_filename>
```

`if: always()` is intentional. Phase 3 in `market_watch_live.yml` has a 30-min staleness guard that aborts when the workflow runs too late (e.g., manual re-trigger hours after the cron target). The translator's output is still worth archiving in that case — the publish gate is a downstream decision and shouldn't block historical capture.

Phase 4 was extended from `git add translated_posts.json` to `git add translated_posts.json archive/` with the commit message updated correspondingly.

## Frontend integration (read side)

The frontend consumes via raw GitHub URLs:

- `https://raw.githubusercontent.com/mctunghai-pixel/orange-news-automation/main/archive/index.json`
- `https://raw.githubusercontent.com/mctunghai-pixel/orange-news-automation/main/archive/posts_{YYYY-MM-DD}.json`

The `lib/fetch-orange-news.ts` module exposes `fetchOrangeNews({archiveDays: N})` for the multi-day union path and falls back through the existing mock-data path on any failure. See `CLAUDE.md` in the website repo for the consumer-side details.

## Migration policy

Fresh start from 2026-05-05 (Day 5). Apr 23 – May 3 articles were not migrated — the founder accepted historical loss when scoping Phase 7.1, and there were no retained snapshots to backfill from.
