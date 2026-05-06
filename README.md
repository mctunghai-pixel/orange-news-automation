# Orange News — Automation

Backend pipelines for [www.orangenews.mn](https://www.orangenews.mn) — a Bloomberg-grade Mongolian financial portal. This repo runs on **GitHub Actions cron** + **raw-GitHub-URL data plane**; the frontend (`mctunghai-pixel/orangenews-website`, Next.js on Vercel) consumes the JSON files this repo writes.

## Production state (snapshot 2026-05-06, end of sprint Day 11)

- **10 daily articles** auto-translated from 14 international + native Mongolian sources, edited to Bloomberg-grade Mongolian Cyrillic.
- **2 Mongolian-language sources live** in the daily mix (ikon.mn RSS + Montsame HTML scraper), Phase 6.1.5 ship 2026-05-06.
- **33 curated YouTube videos** refreshed every 2 hours from 6 financial channels (Bloomberg Television, WSJ, Reuters, FT, CNBC, World Bank Group), Phase 7.3 ship.
- **MSE.mn data** (8 datasets) refreshed multiple times/day via Server Actions endpoint, Phase 6.2.
- **Article archive** (per-day snapshots, Phase 7.1) feeds the `/articles/[slug]` route, `/category/[cat]` page, and `/rss.xml` 7-day window.
- **Slack failure notifications** wired into all 4 production workflows (Phase 8.1 Track A) — gated on `SLACK_WEBHOOK_URL` repo secret.

## Production cron pipelines

| Workflow | Cron | Purpose |
|---|---|---|
| `.github/workflows/orange_news.yml` | `0 22 * * *` (daily, 22:00 UTC = 06:00 MNT) | RSS collect → translate → image gen → FB publish → archive snapshot. Pipeline runtime ~5-9 min. |
| `.github/workflows/market_watch_live.yml` | `0 23 * * *` (daily, 23:00 UTC = 07:00 MNT) | Translator + Live Market Watch FB publish (separate cadence to hit the morning briefing slot). 30-min staleness guard. |
| `.github/workflows/mse_update.yml` | `0 2,3,4,8,9 * * 1-5` (5 fires/weekday) | MSE data refresh; redundant slots catch GHA scheduler skips (Day 5 lesson). |
| `.github/workflows/youtube_update.yml` | `0 */2 * * *` (every 2 hours) | YouTube video feed refresh; ~24 quota units/day = ~0.24% of free 10K. |
| `.github/workflows/market_data_update.yml` | (separate, 30-min cadence) | FX + commodities + index data via Mongolbank + Yahoo + ExchangeRate API. |

All workflows include the Phase 8.1 Track A Slack-on-failure step (gated on `SLACK_WEBHOOK_URL` secret).

## Repo layout

| Path | Purpose |
|---|---|
| `orange_rss_collector.py` | quota-enforced multi-source candidate selection; calls `montsame_scraper.fetch_articles()` after the 13 RSS feeds |
| `orange_translator.py` | Gemini Pro primary + Claude Haiku fallback; native-Mongolian passthrough at line 1473 |
| `montsame_scraper.py` | Phase 6.1.5 — HTML scraper for Mongolian content (Montsame `/mn/more/10` Economy + `/mn/more/16` Mining) |
| `mse_data_fetcher.py` | Phase 6.2 — mse.mn Server Actions endpoint, 8 datasets |
| `market_data_fetcher.py` | Phase 5 — FX + index + commodity + crypto data |
| `youtube_fetcher.py` | Phase 7.3 — YouTube RSS discovery + Data API duration enrichment |
| `archive_writer.py` | Phase 7.1 — per-day article archive snapshots |
| `image_generator.py` | per-post AI image generation |
| `fb_poster.py` / `fb_poster_live.py` | scheduled Facebook publishing |
| `docs/` | per-feature reference docs (deep dives) |
| `archive/` | per-day article snapshots + index |
| `backups/` | local pre-edit snapshots (gitignored) |

## Per-feature docs (`docs/`)

| File | Phase | What it covers |
|---|---|---|
| `archive_phase7.1.md` | 7.1 | Per-day snapshot writer, .gitignore allowlist gotcha, mtime guard |
| `mse_phase6.2_endpoint.md` | 6.2 | mse.mn Server Actions reverse-engineering, action-ID rotation, RSC parsing pitfalls |
| `montsame_phase6.1.5.md` | 6.1.5 | HTML scraper selectors, anti-bot signals, maintenance playbook |
| `youtube_phase7.3.md` | 7.3 | Hybrid RSS + Data API source strategy, Bloomberg disambiguation, quota math |
| `translator_logging_spec.md` | 6.x | Translator pipeline logging conventions |

## Sprint to Commercialization (Day 1-11)

Multiple "Day N" sessions ran on the same calendar day under sprint cadence; the table below is session-anchored, not strictly calendar-anchored.

| Day | Backend ship | Phase |
|---|---|---|
| 5 (2026-05-05) | `archive_writer.py` + Phase 3.5 in workflows + `.gitignore` allowlist; readability CI fix | 7.1 |
| 6 (2026-05-06) | (frontend-only this day) | 7.2.1, 7.3 reservation |
| 7 | Slack failure-notify step in 3 workflows | 8.1 Track A |
| 8 | `youtube_fetcher.py` + `youtube_update.yml` (2-hour cron) | 7.3 Checkpoint A |
| 9 | `montsame_scraper.py` + `orange_rss_collector.py` integration hook | 6.1.5 |
| 10 | (frontend-only this day) | 9.1 sales deck |
| 11 | (frontend lint cleanup + this README) | T1-T5 |
| 12 | (frontend-only — Phase 9.2 customer outreach kit in `docs/sales/`) | 9.2 |
| 13 | (founder review session — no engineer commits) | (founder day) |
| 14 | (frontend-only — Phase 9.3 demo preparation, sprint COMPLETE) | 9.3 |

**🎯 Sprint COMPLETE (Day 14, 2026-05-06).** Production state: ready for first commercial customer onboarding. See the frontend repo's `CLAUDE.md` for the full sprint state + founder review queue. The comprehensive Day 1-14 retrospective lives at `orangenews-website/docs/sales/sprint_retrospective.md`.

**Outstanding founder activations (decoupled from sprint completion):**
- `SLACK_WEBHOOK_URL` repo secret — Day 11 canary diagnosis confirmed GitHub API healthy. Founder needs to re-run `gh secret set SLACK_WEBHOOK_URL --body "<webhook URL>" -R mctunghai-pixel/orange-news-automation` (verified working via TEST_CANARY round-trip).
- `RESEND_API_KEY` + `RESEND_AUDIENCE_ID` Vercel env vars — Phase 7.2.1 Subscribe still 503 until set; backend repo unaffected.
- FB token migration to long-lived System User token (Day 13 spec; backend `FB_ACCESS_TOKEN` secret swap when ready).

## Operational footprint

- **5 GitHub Actions workflows** (the 4 cron pipelines above + `market_data_update.yml`).
- **5 repo Actions secrets**: `ANTHROPIC_API_KEY`, `FB_ACCESS_TOKEN`, `FB_PAGE_ID`, `GEMINI_API_KEY`, `YOUTUBE_API_KEY`. (`SLACK_WEBHOOK_URL` pending founder action.)
- **Data plane**: 5 JSON files at repo root (`translated_posts.json`, `market_data.json`, `mse_data.json`, `youtube_data.json`, `top_news.json`) + per-day snapshots in `archive/`. All served via raw.githubusercontent.com to the frontend. No database, no separate hosting.
- **Total CI time**: ~30-40 min/month across all workflows (well within free tier).
- **External API cost**: ~USD 40-70/month (Gemini + Claude + Resend). YouTube Data API free tier is sufficient.
