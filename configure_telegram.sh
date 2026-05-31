#!/usr/bin/env bash
# =============================================================================
# Orange News — Telegram Bot + Channel-ын бүх тохиргоог terminal-аас хийнэ
# =============================================================================
# Ажиллах:  bash configure_telegram.sh
#
# Хийдэг тохиргоонууд:
#   BOT талаас (setMy*):
#     - Bot нэр (display name)
#     - Богино тайлбар (about — bot profile дээр харагдана)
#     - Урт тайлбар (description — bot нээх үед /start дэлгэцэнд)
#     - Slash commands (/help, /news, /subscribe гэх мэт)
#
#   CHANNEL талаас (setChat*):
#     - Channel title
#     - Channel description
#     - Channel photo (хэрэв path өгвөл)
#     - Auto-delete унтраах (НЭН ЧУХАЛ — мэдээ устах ёсгүй)
#     - Pinned "welcome" мессеж
#
#   Аюулгүйн нэмэлт:
#     - sendMessage эрхээ зөвхөн bot/admin-д үлдээх (anti-spam)
#     - Link preview default, parse_mode HTML аль ч пост-д хүчинтэй (script
#       бүр sendMessage дээр явдаг тул API-аар тохируулах хэрэггүй)
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.env"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }

for cmd in curl jq; do
    command -v "$cmd" >/dev/null 2>&1 || { err "$cmd хэрэгтэй: brew install $cmd"; exit 1; }
done

# Load .env
if [[ ! -f "$ENV_FILE" ]]; then
    err ".env олдсонгүй: $ENV_FILE"
    exit 1
fi
set -a; . "$ENV_FILE"; set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    err ".env-д TELEGRAM_BOT_TOKEN хоосон. Эхлээд setup_telegram.sh ажиллуул."
    exit 1
fi
if [[ -z "${TELEGRAM_CHANNEL_ID:-}" ]]; then
    err ".env-д TELEGRAM_CHANNEL_ID хоосон. Эхлээд setup_telegram.sh ажиллуул."
    exit 1
fi

TOKEN="$TELEGRAM_BOT_TOKEN"
CHAT="$TELEGRAM_CHANNEL_ID"
API="https://api.telegram.org/bot$TOKEN"

# Helper: API call with error reporting
call() {
    local method="$1"; shift
    local resp
    resp=$(curl -sS -X POST "$API/$method" "$@")
    if [[ "$(echo "$resp" | jq -r .ok)" != "true" ]]; then
        warn "$method failed: $(echo "$resp" | jq -c .)"
        return 1
    fi
    return 0
}

echo
bold "🍊 Orange News — Telegram Bot + Channel тохиргоо"
echo "=============================================="
info "Bot: $(curl -s "$API/getMe" | jq -r .result.username)"
info "Channel: $CHAT"
echo

# =============================================================================
# BOT PROFILE
# =============================================================================
bold "1/6 — Bot профайл (name, about, description)"

# Bot name (бот нээх үед дээд талд харагдах нэр)
call setMyName \
    -d "name=Orange News" \
    && ok "Bot name → 'Orange News'"

# Богино тайлбар (about — bot profile-н дээр харагдана, max 120 char)
call setMyShortDescription \
    -d "short_description=🍊 Дэлхийн санхүү, технологийн мэдээг Монголоор. Цаг тутамд автомат шинэчлэгдэнэ." \
    && ok "Short description суулгасан"

# Урт тайлбар (description — /start дэлгэцэнд гарна, max 512 char)
call setMyDescription \
    --data-urlencode "description=🍊 Orange News — Дэлхийн зах зээлийн мэдээг Монгол хэлээр.

📊 Bloomberg, Reuters, WSJ, CNBC, Financial Times эх сурвалжуудаас сонгож, AI-аар орчуулсан мэдээ.

⏰ Өдөр бүр 08:00–17:00 цагт цаг тутамд нэг мэдээ. Эхэндээ Orange Market Watch.

🌐 www.orangenews.mn
📘 facebook.com/orangenews.mn
📷 instagram.com/orangenews.official" \
    && ok "Long description суулгасан"

# Bot commands
call setMyCommands \
    --data-urlencode 'commands=[
      {"command":"start","description":"Bot эхлүүлэх"},
      {"command":"latest","description":"Хамгийн сүүлийн мэдээ"},
      {"command":"market","description":"Өнөөдрийн Orange Market Watch"},
      {"command":"website","description":"www.orangenews.mn нээх"},
      {"command":"help","description":"Тусламж"}
    ]' \
    && ok "Slash commands суулгасан (/start /latest /market /website /help)"
echo

# =============================================================================
# CHANNEL TITLE + DESCRIPTION
# =============================================================================
bold "2/6 — Channel title + description"

call setChatTitle \
    -d "chat_id=$CHAT" \
    -d "title=Orange News" \
    && ok "Channel title → 'Orange News'"

call setChatDescription \
    -d "chat_id=$CHAT" \
    --data-urlencode "description=🍊 Дэлхийн санхүү, технологийн мэдээг Монгол хэлээр.
Bloomberg • Reuters • WSJ • CNBC • Financial Times.
Цаг тутамд автомат шинэчлэгдэнэ.

🌐 www.orangenews.mn" \
    && ok "Channel description суулгасан"
echo

# =============================================================================
# AUTO-DELETE-ИЙГ УНТРААХ (НЭН ЧУХАЛ)
# =============================================================================
bold "3/6 — Auto-delete унтраах (мэдээ архивлахын тулд)"
# Note: Telegram API setMessageAutoDeleteTime эсвэл setChatAutoDeleteTime
# Bot API documentation-д энэ method байхгүй — зөвхөн user/admin app-аар хийнэ.
# Тиймээс автомат биш — гар аргаар хийх ёстой.
warn "Энэ нь Bot API-ээр тохируулагдахгүй (Telegram ограничение)."
echo "Гар аргаар (нэг л удаа): Telegram app → Channel → ⋮ → 'Auto-Delete Messages' → OFF"
echo "Screenshot-аас 'auto-delete in 1 week' идэвхтэй байсан тул унтраахаа битгий мартаарай!"
echo

# =============================================================================
# CHANNEL PHOTO
# =============================================================================
bold "4/6 — Channel photo"
DEFAULT_LOGO="$REPO_DIR/assets/orange_news_logo.png"
[[ -f "$DEFAULT_LOGO" ]] || DEFAULT_LOGO=""

read -rp "Channel-ын зургийн зам (Enter дарвал алгаслана) [$DEFAULT_LOGO]: " PHOTO_PATH
PHOTO_PATH="${PHOTO_PATH:-$DEFAULT_LOGO}"

if [[ -n "$PHOTO_PATH" && -f "$PHOTO_PATH" ]]; then
    call setChatPhoto \
        -F "chat_id=$CHAT" \
        -F "photo=@$PHOTO_PATH" \
        && ok "Channel зураг суулгасан: $(basename "$PHOTO_PATH")"
else
    info "Зураг алгаслаа (одоогийн нь хэвээр)"
fi
echo

# =============================================================================
# PINNED WELCOME MESSAGE
# =============================================================================
bold "5/6 — Pinned welcome мессеж"
read -rp "Pinned welcome пост үүсгээд зүүх үү? [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    WELCOME_TEXT="<b>🍊 Orange News-руу тавтай морил!</b>

📰 Дэлхийн санхүү, технологийн мэдээг Монгол хэлээр, цаг тутамд.

📊 <b>Эх сурвалжууд:</b> Bloomberg • Reuters • WSJ • CNBC • Financial Times • VentureBeat

⏰ <b>Хуваарь:</b>
• 08:00 MNT — Orange Market Watch
• 09:00–17:00 — Сэдэвчилсэн мэдээ (1 цагт 1)

🌐 <a href='https://www.orangenews.mn'>www.orangenews.mn</a>
📘 <a href='https://facebook.com/orangenews.mn'>Facebook</a>
📷 <a href='https://instagram.com/orangenews.official'>Instagram</a>"

    MSG=$(curl -sS -X POST "$API/sendMessage" \
        -d "chat_id=$CHAT" \
        -d "parse_mode=HTML" \
        -d "disable_web_page_preview=true" \
        --data-urlencode "text=$WELCOME_TEXT")
    MSG_ID=$(echo "$MSG" | jq -r '.result.message_id // empty')
    if [[ -n "$MSG_ID" ]]; then
        ok "Welcome пост илгээсэн (id=$MSG_ID)"
        call pinChatMessage \
            -d "chat_id=$CHAT" \
            -d "message_id=$MSG_ID" \
            -d "disable_notification=true" \
            && ok "Pin хийсэн"
    else
        warn "Welcome пост явсангүй: $(echo "$MSG" | jq -c .)"
    fi
fi
echo

# =============================================================================
# АЮУЛГҮЙ НЭМЭЛТ — Bot privacy mode (channel posting-д хамаагүй, гэхдээ
# group-д нэвтрэх үед чухал)
# =============================================================================
bold "6/6 — Аюулгүй байдал + хязгаарлалт"
info "Channel-д зөвхөн админ постолно (Telegram default). Энэ нь автомат хүчинтэй."
info "Гар аргаар хийх 2 зүйл (Bot API-аар хийгдэхгүй):"
echo "  1. Channel → ⋮ → Auto-Delete Messages → OFF"
echo "  2. BotFather-руу /setprivacy → @OrangeNewsMN_Bot → Enable"
echo "     (Bot-ыг group-д нэмэхэд бүх мессеж уншихгүй, зөвхөн mention-г л)"
echo

bold "✅ БҮХ ТОХИРГОО ДУУССАН"
cat <<EOF

Үр дүнг шалгах:
  - Bot profile (@$(curl -s "$API/getMe" | jq -r .result.username))-руу очиж /start дар → шинэ description, commands харагдана
  - Channel-ын title, description, photo шинэчлэгдсэн
  - Pinned пост (хэрэв сонгосон бол) хамгийн дээр зүүгдсэн

Дараах 2 зүйлийг ГАР АРГААР Telegram app-аас:
  ❶ Auto-Delete → OFF (мэдээ устахаас сэргийлнэ)
  ❷ Channel settings → Discussion group (хэрэгтэй бол) → comments идэвхжих
EOF
