#!/usr/bin/env bash
# =============================================================================
# Aravt News — Threads OAuth automated setup
# =============================================================================
# Ажиллах:  bash setup_threads.sh
#
# Энэ скрипт нь Threads OAuth flow-ийн БҮХ curl exchange-уудыг автомат хийнэ.
# Танаас зөвхөн:
#   1. Meta Developer console дээр Threads app үүсгэх (нэг удаагийн, ~5 мин)
#   2. App ID + Secret-ийг paste хийх
#   3. Browser-аас authorization-ын дараах URL-ыг paste хийх
# Дараа нь скрипт:
#   - Code-г exchange хийнэ → short-lived token
#   - Short-lived → long-lived (60 хоног)
#   - User ID авна
#   - .env-д бичнэ
#   - GitHub Secrets суулгана
#   - Dry-run + live тест явуулна
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.env"
REDIRECT_URI="https://www.aravtnews.com/auth/threads/callback"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }
section() { echo; printf "\033[1;34m▌ %s\033[0m\n" "$1"; echo; }

for cmd in curl jq python3; do
    command -v "$cmd" >/dev/null 2>&1 || { err "$cmd хэрэгтэй: brew install $cmd"; exit 1; }
done

echo
bold "🧵 Threads OAuth setup (automated)"
echo "===================================="

# =============================================================================
# Step 1 — Meta Developer console-д Threads app үүсгэх
# =============================================================================
section "АЛХАМ 1/5 — Meta Developer console (~5 мин)"

cat <<EOF

🔗 Browser-аар нээ: https://developers.facebook.com/apps

1) "Create App" дар
   Use case: "Access the Threads API"
   App нэр: "Aravt News"
   Click "Create App"

2) Зүүн талын цэснээс "Use cases" → "Customize" дар
   "Threads API" → "Customize" → "Add" дар

3) "Permissions" tab дотроос дараах эрхүүдийг "Add" хийнэ:
   ✓ threads_basic
   ✓ threads_content_publish

4) Зүүн талын "App settings" → "Basic" дар
   ┌─────────────────────────────────────────────────┐
   │ App ID:      <ХУУЛНА> (16 оронтой тоо)          │
   │ App Secret:  "Show" дарж <ХУУЛНА>               │
   └─────────────────────────────────────────────────┘

5) Зүүн талын "Use cases" → "Threads API" → "Settings" дар
   "Redirect Callback URLs" хэсэгт дараахыг нэм:
       $REDIRECT_URI
   Save changes

EOF

read -rp "Дээрх 5 алхам дууссан уу? Enter дар > " _

# =============================================================================
# Step 2 — App ID + Secret paste
# =============================================================================
section "АЛХАМ 2/5 — App ID + Secret"
read -rp "App ID: " APP_ID
APP_ID="$(echo "$APP_ID" | tr -d '[:space:]')"
read -rp "App Secret: " APP_SECRET
APP_SECRET="$(echo "$APP_SECRET" | tr -d '[:space:]')"

if [[ -z "$APP_ID" || -z "$APP_SECRET" ]]; then
    err "App ID эсвэл Secret хоосон байна"
    exit 1
fi
ok "App тохиргоо хүлээж авав"

# =============================================================================
# Step 3 — Authorization URL
# =============================================================================
section "АЛХАМ 3/5 — Browser-аар Authorize"

AUTH_URL="https://threads.net/oauth/authorize?client_id=${APP_ID}&redirect_uri=${REDIRECT_URI}&scope=threads_basic,threads_content_publish&response_type=code"

cat <<EOF

Browser-аар дараах URL-ыг нээ:

$AUTH_URL

→ Threads account-ийн (@aravtnews) login
→ "Authorize" дар
→ "This site can't be reached" гэх 404 хуудас гарна — ЭНЭ НЬ ХЭВИЙН ҮЙЛДЭЛ
→ Browser-ын ADDRESS BAR-аас БҮТЭН URL-ыг хуулж эндээ paste хий
   Жишээ: https://www.aravtnews.com/auth/threads/callback?code=AQBx-hBs...#_

EOF

# Try to open browser automatically
if command -v open >/dev/null 2>&1; then
    info "Browser автомат нээж байна..."
    open "$AUTH_URL"
fi

echo
read -rp "Browser-аас БҮТЭН URL-ыг paste: " REDIRECT_URL_WITH_CODE

# Extract code from URL
CODE=$(echo "$REDIRECT_URL_WITH_CODE" | python3 -c "
import sys, urllib.parse
url = sys.stdin.read().strip()
parsed = urllib.parse.urlparse(url)
qs = urllib.parse.parse_qs(parsed.query)
code = qs.get('code', [''])[0]
# Strip the #_ suffix Threads appends
code = code.replace('#_', '')
print(code)
")

if [[ -z "$CODE" || ${#CODE} -lt 20 ]]; then
    err "Code олдсонгүй. URL дотор ?code=... байгаа эсэхийг шалга."
    exit 1
fi
ok "Authorization code хүлээж авав (1 цагийн дотор хүчинтэй)"

# =============================================================================
# Step 4 — Exchange code → short-lived → long-lived token
# =============================================================================
section "АЛХАМ 4/5 — Token exchange (автомат)"

info "Short-lived token авч байна..."
SHORT_RESP=$(curl -sS -X POST "https://graph.threads.net/oauth/access_token" \
    -F "client_id=$APP_ID" \
    -F "client_secret=$APP_SECRET" \
    -F "grant_type=authorization_code" \
    -F "redirect_uri=$REDIRECT_URI" \
    -F "code=$CODE")

SHORT_TOKEN=$(echo "$SHORT_RESP" | jq -r '.access_token // empty')
USER_ID=$(echo "$SHORT_RESP" | jq -r '.user_id // empty')

if [[ -z "$SHORT_TOKEN" ]]; then
    err "Short-lived token авч чадсангүй:"
    echo "$SHORT_RESP" | jq .
    exit 1
fi
ok "Short-lived token (~1 цаг) хүлээж авав"
ok "Threads User ID: $USER_ID"

info "Long-lived token-руу (60 хоног) солих..."
LONG_RESP=$(curl -sS -G "https://graph.threads.net/access_token" \
    --data-urlencode "grant_type=th_exchange_token" \
    --data-urlencode "client_secret=$APP_SECRET" \
    --data-urlencode "access_token=$SHORT_TOKEN")

LONG_TOKEN=$(echo "$LONG_RESP" | jq -r '.access_token // empty')
EXPIRES_IN=$(echo "$LONG_RESP" | jq -r '.expires_in // empty')

if [[ -z "$LONG_TOKEN" ]]; then
    err "Long-lived token авч чадсангүй:"
    echo "$LONG_RESP" | jq .
    exit 1
fi
ok "Long-lived token хүлээж авлаа ($((EXPIRES_IN / 86400)) хоног хүчинтэй)"

# Verify token works
VERIFY=$(curl -sS "https://graph.threads.net/v1.0/me?fields=id,username&access_token=$LONG_TOKEN")
USERNAME=$(echo "$VERIFY" | jq -r '.username // empty')
if [[ -z "$USERNAME" ]]; then
    err "Token verification алдаа:"
    echo "$VERIFY" | jq .
    exit 1
fi
ok "Verified: @$USERNAME (ID: $USER_ID)"

# =============================================================================
# Step 5 — .env + GitHub Secrets + Test
# =============================================================================
section "АЛХАМ 5/5 — .env шинэчлэх + тест"

set_env_var() {
    local key="$1" val="$2"
    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i.bak "s|^$key=.*|$key=$val|" "$ENV_FILE"
    else
        echo "$key=$val" >> "$ENV_FILE"
    fi
}
set_env_var "THREADS_ACCESS_TOKEN" "$LONG_TOKEN"
set_env_var "THREADS_USER_ID" "$USER_ID"
rm -f "$ENV_FILE.bak"
ok ".env шинэчлэгдлээ"

# Dry-run
info "Локал dry-run тест..."
set -a; . "$ENV_FILE"; set +a
export ENABLE_THREADS_PUBLISHING=1
export THREADS_PUBLISH_ENABLED=true
export DRY_RUN=true
if python3 "$REPO_DIR/threads_runner.py" --idx 1; then
    ok "Dry-run амжилттай"
else
    err "Dry-run алдаа"; exit 1
fi

# Live test
echo
read -rp "Жинхэнэ тест пост (idx=1) Threads-руу илгээх үү? [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    export DRY_RUN=false
    python3 "$REPO_DIR/threads_runner.py" --idx 1 && ok "Test пост Threads-д орлоо!"
fi

# GitHub Secrets
echo
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    cd "$REPO_DIR"
    echo "$LONG_TOKEN" | gh secret set THREADS_ACCESS_TOKEN
    echo "$USER_ID"    | gh secret set THREADS_USER_ID
    gh variable set THREADS_PUBLISH_ENABLED --body "true" 2>/dev/null || true
    ok "GitHub Secrets + Variable суулгалаа"
else
    warn "gh CLI байхгүй — гар аргаар нэмнэ:"
    echo "  Secrets:    THREADS_ACCESS_TOKEN = <token>, THREADS_USER_ID = $USER_ID"
    echo "  Variables:  THREADS_PUBLISH_ENABLED = true"
fi

echo
bold "🎉 БҮГД БЭЛЭН"
cat <<EOF

Token-ийн менежмент:
  - Long-Lived token = $((EXPIRES_IN / 86400)) хоног хүчинтэй
  - 60 хоног дотор refresh хийгдэх ёстой
  - Calendar reminder: $(date -v+50d '+%Y-%m-%d' 2>/dev/null || date -d '+50 days' '+%Y-%m-%d') — token refresh
  - Refresh helper: publishers/threads.py::refresh_long_lived_token()

Маргааш 08:00 MNT-ээс эхэлж цаг тутамд нэг пост Threads-руу автомат орно.
EOF
