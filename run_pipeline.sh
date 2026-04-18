#!/bin/bash
# =============================================================================
# Orange News Pipeline v7 FINAL
# =============================================================================
# Бүх засвар нэгтгэсэн эцсийн хувилбар
#
# Usage:
#   TEST mode:  ./run_pipeline.sh
#   LIVE mode:  ./run_pipeline.sh --live
#
# Цагийн хуваарь (GitHub Actions):
#   UTC 00:15 = Монгол цагаар 08:15 эхэлнэ
#   Pipeline 30 минут ажиллаж дуусна
#   Эхний пост (Market Watch) ~09:00 Монгол цагт шууд нийтлэгдэнэ
#   Бусад постууд 10:00, 11:00, 12:00 ... 17:00 хүртэл
# =============================================================================

set -e
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
export TZ=Asia/Ulaanbaatar

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LIVE_MODE=false
if [[ "$1" == "--live" ]]; then
    LIVE_MODE=true
fi

LOG_FILE="pipeline_log.txt"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $1" | tee -a "$LOG_FILE"
}

# =============================================================================
# ENV CHECK
# =============================================================================

if [[ "$LIVE_MODE" == true ]]; then
    if [[ -z "$FB_PAGE_ID" || -z "$FB_ACCESS_TOKEN" || -z "$ANTHROPIC_API_KEY" ]]; then
        echo "❌ LIVE mode requires: ANTHROPIC_API_KEY, FB_PAGE_ID, FB_ACCESS_TOKEN"
        exit 1
    fi
else
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        echo "❌ ANTHROPIC_API_KEY is not set"
        exit 1
    fi
fi

echo ""
echo "🍊 =================================================="
echo "🍊  Orange News Pipeline v7 FINAL"
echo "🍊  $(date '+%Y-%m-%d %H:%M') ($(date +%Z))"
echo "🍊  Mode: $( [[ "$LIVE_MODE" == true ]] && echo 'LIVE 🔴' || echo 'TEST 🟡')"
echo "🍊 =================================================="
echo ""

# =============================================================================
# Clean old files
# =============================================================================

log "🗑️  Хуучин файлуудыг цэвэрлэж байна..."
rm -f top_news.json translated_posts.json
log "✅ Цэвэрлэлт дууслаа"
echo ""

# =============================================================================
# PHASE 1: RSS COLLECT
# =============================================================================

echo "▶ PHASE 1: RSS цуглуулж байна..."
python3 orange_rss_collector.py
echo "✅ Phase 1 → top_news.json"
echo ""

# =============================================================================
# PHASE 1.5: MARKET DATA FETCH (шинэ v7.1)
# =============================================================================

echo "▶ PHASE 1.5: Market Data татаж байна (Монголбанк + Yahoo Finance)..."
python3 market_data_fetcher.py || echo "⚠️ Market data алдаа — fallback text ашиглана"
echo ""

# =============================================================================
# PHASE 2: TRANSLATE (v7 — Market Watch + AI smell хориг + full_post)
# =============================================================================

echo "▶ PHASE 2: Translator v7 — Market Watch + орчуулга..."
python3 orange_translator.py
echo "✅ Phase 2 → translated_posts.json"
echo ""

# =============================================================================
# PHASE 2.5: IMAGE GENERATE
# =============================================================================

echo "▶ PHASE 2.5: Image Generator v7..."
python3 image_generator.py
echo "✅ Phase 2.5 → assets/generated/"
echo ""

# =============================================================================
# PHASE 3: FACEBOOK POST
# =============================================================================

echo "▶ PHASE 3: Facebook Poster v7..."
if [[ "$LIVE_MODE" == true ]]; then
    python3 fb_poster.py --live
else
    python3 fb_poster.py
fi
echo "✅ Phase 3 дууссан"
echo ""

echo "🍊 =================================================="
echo "🍊  Pipeline дууслаа — $(date '+%H:%M')"
echo "🍊  Log: $SCRIPT_DIR/$LOG_FILE"
echo "🍊 =================================================="
