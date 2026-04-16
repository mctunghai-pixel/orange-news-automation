#!/bin/bash
# Orange News — Full Pipeline v3
# Azurise AI System
# Usage:
#   TEST mode:  ./run_pipeline.sh
#   LIVE mode:  ./run_pipeline.sh --live

set -e
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LIVE_MODE=false
if [[ "$1" == "--live" ]]; then
    LIVE_MODE=true
fi

LOG_FILE="pipeline_log.txt"

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" | tee -a "$LOG_FILE"
}

# ── ENV CHECK ─────────────────────────────────────────────────────────────────
if [[ "$LIVE_MODE" == true ]]; then
    if [[ -z "$FB_PAGE_ID" || -z "$FB_ACCESS_TOKEN" || -z "$ANTHROPIC_API_KEY" ]]; then
        echo "❌ LIVE mode requires: ANTHROPIC_API_KEY, FB_PAGE_ID, FB_ACCESS_TOKEN"
        exit 1
    fi
else
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        echo "❌ ANTHROPIC_API_KEY is not set."
        exit 1
    fi
fi

echo ""
echo "🍊 =================================================="
echo "🍊  Orange News Pipeline v3 — $(date '+%Y-%m-%d %H:%M')"
echo "🍊  Mode: $( [[ "$LIVE_MODE" == true ]] && echo 'LIVE 🔴' || echo 'TEST 🟡')"
echo "🍊 =================================================="
echo ""

# ── ХУУЧИН ФАЙЛУУДЫГ УСТГА ───────────────────────────────────────────────────
log "🗑️  Хуучин файлуудыг цэвэрлэж байна..."
rm -f top_news.json translated_posts.json
log "✅ Цэвэрлэлт дууслаа"
echo ""

# ── PHASE 1 — RSS COLLECT ─────────────────────────────────────────────────────
echo "▶ PHASE 1: RSS цуглуулж байна..."
python3 orange_rss_collector.py
echo ""
echo "✅ Phase 1 complete → top_news.json"
echo ""

# ── PHASE 2 — TRANSLATE ───────────────────────────────────────────────────────
echo "▶ PHASE 2: Claude-аар орчуулж байна..."
python3 orange_translator.py
echo ""
echo "✅ Phase 2 complete → translated_posts.json"
echo ""

# ── PHASE 2.5 — IMAGE GENERATE ───────────────────────────────────────────────
echo "▶ PHASE 2.5: Зурагнууд үүсгэж байна..."
python3 image_generator.py
echo ""
echo "✅ Phase 2.5 complete → assets/generated/"
echo ""

# ── PHASE 3 — FACEBOOK POST ───────────────────────────────────────────────────
echo "▶ PHASE 3: Facebook-т постлож байна..."
if [[ "$LIVE_MODE" == true ]]; then
    python3 fb_poster.py --live
else
    python3 fb_poster.py
fi
echo ""
echo "✅ Phase 3 complete"
echo ""

echo "🍊 =================================================="
echo "🍊  Pipeline дууслаа — $(date '+%Y-%m-%d %H:%M')"
echo "🍊  Log: $SCRIPT_DIR/$LOG_FILE"
echo "🍊 =================================================="
echo ""
