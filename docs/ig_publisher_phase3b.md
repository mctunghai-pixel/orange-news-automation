# IG Publisher — Phase 3B Runbook

**Status:** Phase 3B.1 in progress. No live IG posts yet.
**Files:** `ig_runner.py`, `.github/workflows/ig_publisher_hourly.yml`, `.github/workflows/media_publisher.yml` (added in commit 4).

This doc covers operating the IG publisher safely during Phase 3B.1
verification and after Phase 3B.2 goes live. The goal is to make the
gating model legible and the kill switch unambiguous.

## Why this doc exists

Three things are not obvious from reading the code cold:

1. **Why there are four gates instead of one.** Each gate covers a
   different failure mode: a global panic-button (kill switch), per-run
   dispatch intent (ENABLE_IG_PUBLISHING), upstream-state drift
   (cross-check), and "rehearse without posting" (DRY_RUN). Removing any
   one weakens a specific scenario; see the table below.

2. **Why the kill switch is default-disabled.** If the repo variable is
   ever accidentally deleted, an absent value reads as empty string,
   which the runner treats as "kill switch engaged." This means the
   safe fallback is "do nothing" — never "post live."

3. **Why cross-check failure does not block.** A flaky `/me/media`
   endpoint must not brick the publisher. The cross-check is
   defense-in-depth, not a primary gate. Network errors and non-200
   responses log a warning and proceed; the local state file remains
   the primary idempotency mechanism.

## Gating model (in order)

| Gate | Source | Default | Engaged when | Effect |
|------|--------|---------|--------------|--------|
| `IG_PUBLISH_ENABLED` | repo variable | not set → blocked | value ≠ `"true"` (case-insensitive) | exit 0 immediately, no work |
| `ENABLE_IG_PUBLISHING` | workflow_dispatch input | `false` → `"0"` | env ≠ `"1"` | exit 0, no work |
| IG `/me/media` cross-check | live API | n/a | first 80 chars of caption match a recent IG post | record `via_cross_check=True`, exit 0 |
| `DRY_RUN` | env (not yet set in workflow) | `"true"` | env ≠ `"false"` | log payload, exit 0 |

**Live publish requires all four gates to pass.** As of Phase 3B.1, the
workflow does not set `DRY_RUN` at all, so the runner falls through to
the `"true"` default — no live post is possible from any commit in 3B.1.

## Setting the kill switch

GitHub repo settings:

1. Navigate to **Settings → Secrets and variables → Actions → Variables**.
2. Add (or edit) repository variable `IG_PUBLISH_ENABLED`.
3. Value: `false` (Phase 3B.1 default — kill switch engaged).
4. Phase 3B.2 go-live: change value to `true`.

To engage the kill switch fast (fastest mitigation, ~5 seconds):

1. Same path as above.
2. Set `IG_PUBLISH_ENABLED=false` (or delete the variable).
3. Next workflow run exits at the kill switch with log line
   `🛑 kill switch: IG_PUBLISH_ENABLED="false" — exiting without work`.

## Phase 3B.1 verification dispatches

After all five 3B.1 commits land, run these workflow_dispatches before
considering 3B.1 complete:

**Dispatch A — `media_publisher.yml`**
- Trigger: workflow_dispatch on `media_publisher.yml`.
- Verify: `media-public` orphan branch has today's images. `curl -I` an
  image URL externally; expect 200.

**Dispatch B — kill switch blocks**
- Variable: `IG_PUBLISH_ENABLED=false` (or unset).
- Trigger: `ig_publisher_hourly.yml` workflow_dispatch with
  `enable_publishing=true`.
- Verify: runner logs `🛑 kill switch: ... — exiting without work` and
  exits before doing anything else. Slack notification fires (commit 5)
  with status "skipped: kill switch."

**Dispatch C — full payload, no publish**
- Variable: `IG_PUBLISH_ENABLED=true`.
- Trigger: `ig_publisher_hourly.yml` workflow_dispatch with
  `enable_publishing=true`.
- Verify: runner proceeds past kill switch + ENABLE_IG_PUBLISHING gates,
  performs `/me/media` cross-check (logs result), hits DRY_RUN gate,
  logs the would-be payload, exits without calling `/media_publish`.
- After verifying the payload looks correct, set `IG_PUBLISH_ENABLED=false`
  again before leaving the verification window.

3B.1 exit criteria: all three dispatches green, founder eyeballs the
dispatch C payload, Slack wiring confirmed, state-file commit-back works
without push conflicts.

## Rollback paths (Phase 3B.1)

| Scenario | Mitigation | Time |
|----------|-----------|------|
| Bad post on IG (after 3B.2 go-live) | Manual delete in IG app | seconds |
| Need to stop all future runs | Set `IG_PUBLISH_ENABLED=false` | ~5 sec |
| State file corrupt | Edit `logs/ig_publish_state.json`, commit revert | minutes |
| Workflow itself broken | GitHub Actions UI → Disable workflow | ~30 sec |
| Need full rollback | Restore from `backups/pre-phase3b1-20260510/`, see MANIFEST | minutes |

## Out of scope (Phase 3B.2 / 3C)

- Flipping `DRY_RUN` default to `"false"` (workflow change) → Phase 3B.2 commit 6.
- `workflow_run` trigger linking `media_publisher.yml` to `orange_news.yml` → Phase 3C.
- Hourly cron schedule on `ig_publisher_hourly.yml` → Phase 3C.

## Forbidden surface (Phase 3B as a whole)

`fb_poster.py` and `.github/workflows/orange_news.yml` must remain
byte-identical through every Phase 3B commit. Baseline blob SHAs are
recorded in `backups/pre-phase3b1-20260510/MANIFEST.txt`. Verify after
each commit:

```sh
git rev-parse HEAD:fb_poster.py
git rev-parse HEAD:.github/workflows/orange_news.yml
```
