# LOGGING SPECIFICATION FOR orange_translator.py

================================================
LOGGING SPECIFICATION FOR orange_translator.py
================================================

Per-article log entry — Python dict with these keys:

    article_index             (int, 0-9)
    article_title_en          (str, first 80 chars of English title)
    api_used                  (str, one of: "gemini", "claude", "failed")
    gemini_attempted          (bool, always True unless GEMINI_API_KEY missing from env)
    gemini_success            (bool, True if valid JSON returned)
    gemini_error              (str or None, error message)
    gemini_latency_ms         (int or None, wall-clock Gemini call time)
    claude_fallback_used      (bool, True if Gemini failed and Claude ran)
    claude_latency_ms         (int or None)
    total_latency_ms          (int, sum if fallback, else just successful one)
    input_tokens_est          (int, rough: len(prompt) // 4)
    output_tokens_est         (int, rough: len(response) // 4)
    cost_estimate_usd         (float, 0.0 for Gemini free tier, ~0.015 for Claude Haiku)
    validation_warnings       (list of str, e.g. "headline too long: 95 chars")
    timestamp_utc             (str, ISO 8601 format)

================================================
END-OF-RUN STDOUT SUMMARY
================================================

Print to stdout in this exact style (plain text, easy to grep in GHA logs):

    ======================================
    Orange News Translator — Run Summary
    ======================================
    Run started:  2026-04-23 08:00:15 UTC
    Run finished: 2026-04-23 08:01:02 UTC
    Duration:     47.2 seconds

    Articles processed: 10
      Gemini success:    8  (80%)
      Claude fallback:   2  (20%)
      Both failed:       0  (0%)

    Latency:
      Gemini avg: 3.1s
      Claude avg: 5.8s
      Total:      47.2s

    Cost estimate:
      Gemini:     $0.000  (free tier)
      Claude:     $0.030  (2 articles x ~$0.015)
      Total:      $0.030

    Validation warnings: 3
      [2] Headline 92 chars (target 60-80)
      [5] Body does not end with Эх сурвалж
      [7] Contains banned phrase аж ахуйн нэгж

    Full log: logs/translation_20260423_0800.json
    ======================================

================================================
LOG FILE ON DISK
================================================

Path: logs/translation_YYYYMMDD_HHMM.json

Top-level structure (JSON):

    run_id              (str, e.g. "20260423_0800")
    started_utc         (str, ISO 8601)
    finished_utc        (str, ISO 8601)
    duration_s          (float)
    model_primary       (str, "gemini-2.0-flash")
    model_fallback      (str, "claude-haiku-4-5-20251001")
    totals              (dict with articles, gemini_success, claude_fallback, both_failed, cost_usd)
    articles            (list of per-article log entries, same schema as above)

================================================
GITIGNORE
================================================

Add "logs/" to .gitignore so run logs don't get committed.
