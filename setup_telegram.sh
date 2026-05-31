#!/usr/bin/env bash
# =============================================================================
# Orange News — Telegram bot бүх setup-ийг автомат хийдэг скрипт
# =============================================================================
# Ажиллах:  bash setup_telegram.sh
#
# Хийдэг зүйл:
#   1. Bot Token-г таны .env-д бичнэ
#   2. Telegram API-аас Channel ID-г автомат олно (Bot-ыг чат-д орсон бүх chat-аас)
#   3. .env-д TELEGRAM_CHANNEL_ID нэмнэ
#   4. GitHub Secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID) суулгана
#   5. GitHub Variable (TELEGRAM_PUBLISH_ENABLED=true) суулгана
#   6. DRY_RUN workflow-г GitHub Actions дээр шууд turshina
#   7. Цаг тутмын live publishing идэвхжүүлнэ
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.env"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }

echo
bold "🍊 Orange News → Telegram setup автоматжуулалт"
echo "============================================="
echo

# -----------------------------------------------------------------------------
# 1. Prerequisites
# -----------------------------------------------------------------------------
for cmd in curl jq python3 git; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        err "$cmd суусан байх ёстой. \`brew install $cmd\` командыг ажиллуул."
        exit 1
    fi
done

if ! command -v gh >/dev/null 2>&1; then
    warn "gh CLI олдсонгүй. Суулгахдаа: brew install gh"
    read -rp "Үргэлжлүүлэх үү? (gh-гүйгээр GitHub Secrets гар аргаар суулгана) [y/N]: " ans
    [[ "$ans" =~ ^[Yy]$ ]] || exit 1
    HAVE_GH=0
else
    HAVE_GH=1
fi

# -----------------------------------------------------------------------------
# 2. Bot Token
# -----------------------------------------------------------------------------
bold "Алхам 1/6 — Bot Token"
echo "BotFather (@BotFather)-ийн өгсөн token-оо энд paste хий"
echo "(Жишээ нь: 1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)"
echo
read -rp "TELEGRAM_BOT_TOKEN: " TOKEN
TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"

if [[ -z "$TOKEN" || ! "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    err "Token формат буруу. Дахин ажиллуулна уу."
    exit 1
fi

# Token validity check
RESP=$(curl -fsS "https://api.telegram.org/bot$TOKEN/getMe" || echo '{"ok":false}')
if [[ "$(echo "$RESP" | jq -r .ok)" != "true" ]]; then
    err "Token хүчингүй. Telegram API хариу: $(echo "$RESP" | jq -c .)"
    exit 1
fi
BOT_USERNAME=$(echo "$RESP" | jq -r '.result.username')
ok "Bot танигдлаа: @${BOT_USERNAME}"
echo

# -----------------------------------------------------------------------------
# 3. Channel ID олох
# -----------------------------------------------------------------------------
bold "Алхам 2/6 — Channel ID олох"
echo "1) Telegram-аа нээ, @${BOT_USERNAME} bot-оо channel-ын ADMIN болго"
echo "   (Channel → Manage → Administrators → Add → @${BOT_USERNAME})"
echo "2) 'Post Messages' эрхийг идэвхжүүл"
echo "3) Тэндээ ямар нэг ТЕСТ мессеж бичээд (өөрөө биш) bot-доо MENTION хий"
echo "   эсвэл channel-д өөр пост нэмэх (Bot-ыг update авах боломжтой болгох)"
echo
read -rp "Бэлэн болсон уу? Enter дар > " _

UPDATES=$(curl -fsS "https://api.telegram.org/bot$TOKEN/getUpdates" || echo '{"ok":false,"result":[]}')

# channel_post -> chat.id олох
CHANNEL_ID=$(echo "$UPDATES" | jq -r '
  .result
  | map(.channel_post.chat // .my_chat_member.chat // empty)
  | map(select(.type=="channel"))
  | unique_by(.id)
  | .[0].id // empty
')

if [[ -z "$CHANNEL_ID" || "$CHANNEL_ID" == "null" ]]; then
    warn "Channel ID авто-олдсонгүй. Гар аргаар оруулна уу."
    echo "  - Public channel: @channelname"
    echo "  - Private channel ID-г олох: t.me/<linkname> руу bot-ыг чатлуулаад,"
    echo "    https://api.telegram.org/bot${TOKEN}/getUpdates -ийг browser-аар нээж 'chat.id' хайна"
    read -rp "TELEGRAM_CHANNEL_ID: " CHANNEL_ID
    CHANNEL_ID="$(echo "$CHANNEL_ID" | tr -d '[:space:]')"
fi

if [[ -z "$CHANNEL_ID" ]]; then
    err "Channel ID хэрэгтэй. Гарлаа."
    exit 1
fi

CHANNEL_TITLE=$(echo "$UPDATES" | jq -r --arg id "$CHANNEL_ID" '
  .result
  | map(.channel_post.chat // .my_chat_member.chat // empty)
  | map(select((.id|tostring)==$id))
  | .[0].title // "unknown"
')
ok "Channel сонгогдлоо: $CHANNEL_TITLE ($CHANNEL_ID)"
echo

# -----------------------------------------------------------------------------
# 4. .env-д бичих
# -----------------------------------------------------------------------------
bold "Алхам 3/6 — .env шинэчлэх"
touch "$ENV_FILE"

# TELEGRAM_BOT_TOKEN
if grep -q "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE"; then
    # macOS sed in-place needs ''
    sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TOKEN|" "$ENV_FILE"
else
    echo "TELEGRAM_BOT_TOKEN=$TOKEN" >> "$ENV_FILE"
fi

if grep -q "^TELEGRAM_CHANNEL_ID=" "$ENV_FILE"; then
    sed -i.bak "s|^TELEGRAM_CHANNEL_ID=.*|TELEGRAM_CHANNEL_ID=$CHANNEL_ID|" "$ENV_FILE"
else
    echo "TELEGRAM_CHANNEL_ID=$CHANNEL_ID" >> "$ENV_FILE"
fi

rm -f "$ENV_FILE.bak"
ok ".env шинэчлэгдлээ"
echo

# -----------------------------------------------------------------------------
# 5. Локал dry-run test
# -----------------------------------------------------------------------------
bold "Алхам 4/6 — Локал dry-run test"
set -a; . "$ENV_FILE"; set +a
if python3 "$REPO_DIR/telegram_poster.py" --idx 1 --dry-run; then
    ok "Dry-run амжилттай"
else
    err "Dry-run алдаа. Үргэлжлүүлэх боломжгүй."
    exit 1
fi
echo

# -----------------------------------------------------------------------------
# 6. Live тест — 1 пост шууд илгээх
# -----------------------------------------------------------------------------
bold "Алхам 5/6 — Жинхэнэ Telegram-руу 1 тест пост"
read -rp "Channel-руу одоо ТЭСТ пост (idx=1) илгээх үү? [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    if python3 "$REPO_DIR/telegram_poster.py" --idx 1; then
        ok "Тест пост Telegram-д орлоо. Channel-аа шалга!"
    else
        err "Live тест алдаа. State file шалгана уу."
        exit 1
    fi
else
    info "Тест алгаслаа"
fi
echo

# -----------------------------------------------------------------------------
# 7. GitHub Secrets + Variables
# -----------------------------------------------------------------------------
bold "Алхам 6/6 — GitHub Secrets + цаг тутмын workflow идэвхжүүлэх"

if [[ "$HAVE_GH" == "1" ]]; then
    cd "$REPO_DIR"
    if ! gh auth status >/dev/null 2>&1; then
        info "gh auth дутуу. Логин руу оруулна:"
        gh auth login
    fi

    echo "$TOKEN" | gh secret set TELEGRAM_BOT_TOKEN
    echo "$CHANNEL_ID" | gh secret set TELEGRAM_CHANNEL_ID
    gh variable set TELEGRAM_PUBLISH_ENABLED --body "true" || warn "variable suulgaj chadsangui (manual hii)"

    ok "GitHub Secrets + Variable суулгагдлаа"

    # state file commit (logs/-г заавал commit хийнэ)
    mkdir -p "$REPO_DIR/logs"
    if [[ -f "$REPO_DIR/logs/telegram_publish_state.json" ]]; then
        git add logs/telegram_publish_state.json 2>/dev/null || true
        git diff --staged --quiet || git commit -m "chore(telegram): seed state from local test [skip ci]" 2>/dev/null || true
    fi

    # Push шинэ файлууд
    git add telegram_poster.py .github/workflows/telegram_publisher_hourly.yml .env.example .gitignore 2>/dev/null || true
    git diff --staged --quiet || {
        git commit -m "feat(telegram): hourly channel publisher v1"
        git push
        ok "Код GitHub-д push хийгдлээ"
    }

    # workflow_dispatch dry-run
    info "Эхний workflow-г GitHub Actions дээр turshina..."
    gh workflow run telegram_publisher_hourly.yml \
        -f enable_publishing=true \
        -f dry_run=true || warn "workflow run амжилтгүй — гар аргаар Actions tab-аас turshi"
else
    cat <<EOF
gh CLI байхгүй тул дараах 3 зүйлийг GitHub Settings → Secrets/Variables хэсэгт гар аргаар:
  Secrets (Repository secrets):
    TELEGRAM_BOT_TOKEN  = $TOKEN
    TELEGRAM_CHANNEL_ID = $CHANNEL_ID
  Variables (Repository variables):
    TELEGRAM_PUBLISH_ENABLED = true

Дараа нь:
  git add telegram_poster.py .github/workflows/telegram_publisher_hourly.yml .env.example .gitignore
  git commit -m "feat(telegram): hourly channel publisher v1"
  git push
EOF
fi

echo
bold "🎉 БҮГД БЭЛЭН"
cat <<EOF
Маргааш UTC 00:00 (MNT 08:00)-аас эхлэн цаг тутамд нэг пост Telegram channel-руу автомат орно.
   - Statе/log: logs/telegram_publish_state.json
   - Workflow: .github/workflows/telegram_publisher_hourly.yml
   - Manual run: gh workflow run telegram_publisher_hourly.yml -f enable_publishing=true -f force_idx=2
EOF
