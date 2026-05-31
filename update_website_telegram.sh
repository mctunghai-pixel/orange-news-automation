#!/usr/bin/env bash
# =============================================================================
# Website footer-д Telegram + QR section нэмэх (1-shot)
# =============================================================================
# Ажиллах: bash update_website_telegram.sh
#
# Хийдэг зүйл:
#   1. gh CLI-аар website repo-г олно (setup_website_grid.sh-тэй ижил)
#   2. public/ folder руу telegram_qr.png-ийг хуулна
#   3. src/components/TelegramFooter.tsx-г хуулна
#   4. Үндсэн layout эсвэл app/page.tsx-д <TelegramFooter /> import нэмнэ
#      (Footer component олдвол түүн дотор; үгүй бол page.tsx-ийн төгсгөлд)
#   5. Diff харуулж, push-ийг зөвшөөрвөл commit + push (Vercel autodeploy)
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
QR_SRC="$REPO_DIR/assets/telegram_qr.png"
COMPONENT_SRC="$REPO_DIR/Vercel/TelegramFooter.tsx"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }

for cmd in gh git jq; do
    command -v "$cmd" >/dev/null 2>&1 || { err "$cmd хэрэгтэй: brew install $cmd"; exit 1; }
done
[[ -f "$QR_SRC" ]] || { err "QR файл олдсонгүй: $QR_SRC"; exit 1; }
[[ -f "$COMPONENT_SRC" ]] || { err "Component олдсонгүй: $COMPONENT_SRC"; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login

echo
bold "📨 Website footer-д Telegram subscribe section нэмэх"
echo "====================================================="
echo

# -----------------------------------------------------------------------------
# 1. Repo сонгох
# -----------------------------------------------------------------------------
USER=$(gh api user --jq .login)
CANDIDATES=$(gh repo list "$USER" --limit 100 --json name,url \
    --jq '.[] | select(.name | test("(?i)orange|news|web|site")) | "\(.name) | \(.url)"')

if [[ -z "$CANDIDATES" ]]; then
    read -rp "Website repo нэр: " REPO_NAME
else
    echo "$CANDIDATES" | nl
    read -rp "Аль вэбсайт репо вэ? [number]: " IDX
    REPO_NAME=$(echo "$CANDIDATES" | sed -n "${IDX}p" | awk -F' \\| ' '{print $1}')
fi

REPO_FULL="$USER/$REPO_NAME"
ok "Repo: $REPO_FULL"

# -----------------------------------------------------------------------------
# 2. Clone
# -----------------------------------------------------------------------------
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
gh repo clone "$REPO_FULL" "$TMPDIR/repo" -- --depth=1 --quiet
cd "$TMPDIR/repo"

# -----------------------------------------------------------------------------
# 3. QR + Component хуулах
# -----------------------------------------------------------------------------
bold "Файлуудыг суулгах"

mkdir -p public
cp "$QR_SRC" public/telegram_qr.png
ok "public/telegram_qr.png суулгасан"

# Component-ыг src/components/ эсвэл components/-д хийх — аль нь байгаа эсэхээс хамаарна
if [[ -d "src/components" ]]; then
    COMPONENT_DEST="src/components/TelegramFooter.tsx"
elif [[ -d "components" ]]; then
    COMPONENT_DEST="components/TelegramFooter.tsx"
elif [[ -d "src/app" ]]; then
    mkdir -p src/components
    COMPONENT_DEST="src/components/TelegramFooter.tsx"
else
    mkdir -p components
    COMPONENT_DEST="components/TelegramFooter.tsx"
fi
cp "$COMPONENT_SRC" "$COMPONENT_DEST"
ok "$COMPONENT_DEST суулгасан"

# -----------------------------------------------------------------------------
# 4. Footer / layout-д import нэмэх
# -----------------------------------------------------------------------------
bold "Footer-руу <TelegramFooter /> нэмэх"

# Хайх footer файл
FOOTER_CANDIDATES=$(grep -rEln \
    --include="*.tsx" --include="*.jsx" \
    -e "footer" -e "Footer" \
    src components app 2>/dev/null | head -10)

echo "Footer/layout файлууд:"
echo "$FOOTER_CANDIDATES" | nl
read -rp "Аль файлд <TelegramFooter /> оруулах вэ? (number, эсвэл Enter — manual): " IDX

if [[ -n "$IDX" ]]; then
    TARGET=$(echo "$FOOTER_CANDIDATES" | sed -n "${IDX}p")
    [[ -f "$TARGET" ]] || { warn "Файл олдсонгүй — manual integrate"; }

    if [[ -f "$TARGET" ]]; then
        # Determine import path
        case "$COMPONENT_DEST" in
            src/components/*) IMP_PATH="@/components/TelegramFooter" ;;
            components/*)     IMP_PATH="@/components/TelegramFooter" ;;
            *) IMP_PATH="./TelegramFooter" ;;
        esac

        # Insert import at top (after last existing import)
        if ! grep -q "TelegramFooter" "$TARGET"; then
            python3 - "$TARGET" "$IMP_PATH" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
imp_path = sys.argv[2]
s = p.read_text(encoding="utf-8")

import_line = f'import TelegramFooter from "{imp_path}"\n'

# 1. Insert import after last import statement
lines = s.split("\n")
last_import = -1
for i, ln in enumerate(lines):
    if ln.strip().startswith("import "):
        last_import = i
if last_import >= 0:
    lines.insert(last_import + 1, import_line.rstrip())
else:
    lines.insert(0, import_line.rstrip())

s = "\n".join(lines)

# 2. Insert <TelegramFooter /> just before closing </footer> tag or end of component
inserted = False
if "</footer>" in s and "<TelegramFooter" not in s:
    s = s.replace("</footer>", "  <TelegramFooter />\n      </footer>", 1)
    inserted = True
elif "<footer" in s and "<TelegramFooter" not in s:
    # Insert right after opening <footer ...>
    s = re.sub(r"(<footer[^>]*>)", r"\1\n      <TelegramFooter />", s, count=1)
    inserted = True

p.write_text(s, encoding="utf-8")
print("✅ Component placed" if inserted else "⚠️ Component імпорт нэмсэн, гэхдээ <footer>-ийн дотор гар аргаар <TelegramFooter /> tag-ыг оруулна уу")
PY
        else
            info "TelegramFooter аль хэдийн import хийгдсэн"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# 5. Diff + push
# -----------------------------------------------------------------------------
bold "Diff:"
git --no-pager diff --stat
echo
git --no-pager diff -- "$COMPONENT_DEST" public/telegram_qr.png 2>/dev/null || true

read -rp "Push хийх үү? Vercel автомат deploy [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    git config user.email "$(gh api user --jq .email // 'mc.tunghai@gmail.com')"
    git config user.name "$USER"
    git add public/telegram_qr.png "$COMPONENT_DEST" "$TARGET" 2>/dev/null || true
    git commit -m "feat(footer): Telegram subscribe section + QR code"
    git push
    ok "Push хийсэн. Vercel deploy эхэлсэн."
else
    info "Push алгасав. Файлуудыг шалга: cd $TMPDIR/repo"
    trap - EXIT
fi
