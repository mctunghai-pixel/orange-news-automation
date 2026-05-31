#!/usr/bin/env bash
# =============================================================================
# Orange News — Дутуу 3 ажлыг 1 скриптээр live болгох
# =============================================================================
# Ажиллах: bash apply_all_changes.sh
#
# Хийдэг 3 алхам:
#   1. orange-news-automation: footer + QR + telegram workflow → main push
#   2. orangenews-website: Latest News 9 → 10 (grid-cols-3 → grid-cols-5)
#   3. orangenews-website: TelegramFooter component + QR + footer integration
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
QR_SRC="$REPO_DIR/assets/telegram_qr.png"
COMPONENT_SRC="$REPO_DIR/Vercel/TelegramFooter.tsx"

# Vercel dashboard-аас тогтоосон website repo нэр
WEBSITE_REPO="mctunghai-pixel/orangenews-website"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }
section() { echo; printf "\033[1;34m%s\033[0m\n" "════════════════════════════════════════"; printf "\033[1;34m%s\033[0m\n" "$1"; printf "\033[1;34m%s\033[0m\n" "════════════════════════════════════════"; echo; }

for cmd in gh git jq; do
    command -v "$cmd" >/dev/null 2>&1 || { err "$cmd хэрэгтэй: brew install $cmd"; exit 1; }
done
gh auth status >/dev/null 2>&1 || { info "gh-д нэвтэрнэ..."; gh auth login; }

[[ -f "$QR_SRC" ]] || { err "QR файл олдсонгүй: $QR_SRC"; exit 1; }
[[ -f "$COMPONENT_SRC" ]] || { err "Component олдсонгүй: $COMPONENT_SRC"; exit 1; }

# =============================================================================
# STEP 1 — orange-news-automation push
# =============================================================================
section "STEP 1/3 — orange-news-automation footer + QR push"

cd "$REPO_DIR"

# Шинэ файлуудыг allowlist gitignore-той эвцэлдүүлэх
git status --short | head -20

# Энэ хавтсаас push хийнэ
FILES_TO_ADD=(
    "fb_poster.py"
    "orange_translator.py"
    "telegram_poster.py"
    "image_generator.py"
    "assets/telegram_qr.png"
    "assets/telegram_qr_bw.png"
    ".github/workflows/telegram_publisher_hourly.yml"
    ".env.example"
    ".gitignore"
    "setup_telegram.sh"
    "configure_telegram.sh"
    "setup_website_grid.sh"
    "update_website_telegram.sh"
    "apply_all_changes.sh"
    "Vercel/TelegramFooter.tsx"
)

for f in "${FILES_TO_ADD[@]}"; do
    [[ -e "$f" ]] && git add "$f" 2>/dev/null || true
done

# Force-add QR even if assets/ glob is gitignored
git add -f assets/telegram_qr.png assets/telegram_qr_bw.png 2>/dev/null || true

if git diff --staged --quiet; then
    info "orange-news-automation: өөрчлөлт байхгүй (өмнө нь push хийгдсэн байх)"
else
    git commit -m "feat: telegram channel + QR code + footer

- Add Telegram QR code to FB post images (image_generator.py)
- Update FOOTER_LINKS with t.me/OrangeNewsMN in fb_poster, translator, telegram_poster
- Add telegram_publisher_hourly.yml workflow
- Add setup/configure scripts for one-shot deployment"
    git push
    ok "orange-news-automation push дууссан"
fi

# =============================================================================
# STEP 2 + 3 — orangenews-website clone + edit + push
# =============================================================================
section "STEP 2+3/3 — orangenews-website grid + footer + QR"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR" 2>/dev/null || true' EXIT

info "$WEBSITE_REPO clone хийж байна..."
gh repo clone "$WEBSITE_REPO" "$TMPDIR/site" -- --depth=1 --quiet
cd "$TMPDIR/site"

# -----------------------------------------------------------------------------
# 2a. Grid 9 → 10
# -----------------------------------------------------------------------------
bold "▸ Latest News 9 → 10 (grid-cols-3 → grid-cols-5)"

# slice(0, 9), take(9), grid-cols-3 хэв шинжтэй файлууд
HITS=$(grep -rEln \
    --include="*.tsx" --include="*.jsx" --include="*.ts" --include="*.js" \
    -e "slice(0, ?9)" \
    -e "slice(0,9)" \
    -e "take(9)" \
    -e "limit: ?9" \
    -e "LATEST_NEWS_LIMIT" \
    -e "Сүүлийн" \
    -e "latestNews" \
    -e "LatestNews" \
    . 2>/dev/null || true)

if [[ -z "$HITS" ]]; then
    warn "9-той pattern олдсонгүй. grid-cols-3-той файлуудыг шалга:"
    grep -rEln --include="*.tsx" --include="*.jsx" "grid-cols-3" . | head -10
    read -rp "Гар аргаар файлын зам бичих (Enter — алгасах): " GRID_FILE
else
    echo "Олдсон файлууд:"
    echo "$HITS" | nl
    echo
    read -rp "Аль файлд 9→10 засна вэ? [number, эсвэл Enter — эхнийх]: " IDX
    if [[ -z "$IDX" ]]; then
        GRID_FILE=$(echo "$HITS" | head -1)
    else
        GRID_FILE=$(echo "$HITS" | sed -n "${IDX}p")
    fi
fi

if [[ -n "${GRID_FILE:-}" && -f "$GRID_FILE" ]]; then
    cp "$GRID_FILE" "$GRID_FILE.bak"
    python3 - "$GRID_FILE" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
orig = s

s = re.sub(r"\.slice\(\s*0\s*,\s*9\s*\)", ".slice(0, 10)", s)
s = re.sub(r"\.take\(\s*9\s*\)",          ".take(10)",     s)
s = re.sub(r"limit:\s*9\b",               "limit: 10",     s)
s = re.sub(r"LATEST_NEWS_LIMIT\s*=\s*9",  "LATEST_NEWS_LIMIT = 10", s)
s = re.sub(r"(\b(?:lg:|md:|sm:|xl:|2xl:)?)grid-cols-3\b", r"\1grid-cols-5", s)

if s != orig:
    p.write_text(s, encoding="utf-8")
    print("✅ Засагдсан:")
    for pat in ["slice(0, 10)", "take(10)", "limit: 10", "LATEST_NEWS_LIMIT = 10", "grid-cols-5"]:
        if pat in s and pat not in orig:
            print(f"   • {pat}")
else:
    print("⚠️  Pattern таарсангүй — файлыг гар аргаар шалга")
PY
    rm "$GRID_FILE.bak"
    ok "Grid file: $GRID_FILE"
else
    warn "Grid өөрчлөлт алгаслаа"
fi
echo

# -----------------------------------------------------------------------------
# 2b. TelegramFooter + QR
# -----------------------------------------------------------------------------
bold "▸ TelegramFooter component + QR суулгах"

mkdir -p public
cp "$QR_SRC" public/telegram_qr.png
ok "public/telegram_qr.png суулгасан"

# Component dest
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

# Footer/layout-д import + tag оруулах
FOOTER_HITS=$(grep -rEln --include="*.tsx" --include="*.jsx" \
    -e "<footer" -e "Footer" \
    src components app 2>/dev/null | grep -v TelegramFooter | head -10 || true)

if [[ -n "$FOOTER_HITS" ]]; then
    echo "Footer/layout файлууд:"
    echo "$FOOTER_HITS" | nl
    read -rp "Аль файлд <TelegramFooter /> оруулах вэ? [number, эсвэл Enter — эхнийх]: " IDX
    if [[ -z "$IDX" ]]; then
        FOOTER_FILE=$(echo "$FOOTER_HITS" | head -1)
    else
        FOOTER_FILE=$(echo "$FOOTER_HITS" | sed -n "${IDX}p")
    fi

    if [[ -f "$FOOTER_FILE" ]]; then
        case "$COMPONENT_DEST" in
            src/components/*) IMP_PATH="@/components/TelegramFooter" ;;
            components/*)     IMP_PATH="@/components/TelegramFooter" ;;
            *) IMP_PATH="./TelegramFooter" ;;
        esac
        python3 - "$FOOTER_FILE" "$IMP_PATH" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
imp_path = sys.argv[2]
s = p.read_text(encoding="utf-8")

if "TelegramFooter" in s:
    print("ℹ️  TelegramFooter аль хэдийн оруулсан")
    sys.exit(0)

import_line = f'import TelegramFooter from "{imp_path}"'
lines = s.split("\n")
last_imp = -1
for i, ln in enumerate(lines):
    if ln.strip().startswith("import "):
        last_imp = i
lines.insert(last_imp + 1 if last_imp >= 0 else 0, import_line)
s = "\n".join(lines)

inserted = False
if "</footer>" in s:
    s = s.replace("</footer>", "  <TelegramFooter />\n      </footer>", 1)
    inserted = True
elif re.search(r"<footer[^>]*>", s):
    s = re.sub(r"(<footer[^>]*>)", r"\1\n      <TelegramFooter />", s, count=1)
    inserted = True

p.write_text(s, encoding="utf-8")
print(f"✅ TelegramFooter оруулсан: {sys.argv[1]}")
if not inserted:
    print("⚠️  <footer> tag олдсонгүй — гар аргаар <TelegramFooter /> tag оруулна уу")
PY
    fi
fi
echo

# -----------------------------------------------------------------------------
# 2c. Diff харуулах
# -----------------------------------------------------------------------------
bold "▸ Diff үзэх"
git --no-pager diff --stat
echo

# -----------------------------------------------------------------------------
# 2d. Push
# -----------------------------------------------------------------------------
read -rp "Бүх өөрчлөлтийг push хийх үү? Vercel автомат deploy [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    git config user.email "$(gh api user --jq .email // 'mc.tunghai@gmail.com')"
    git config user.name "$(gh api user --jq .login)"
    git add -A
    git commit -m "feat: Latest News 5x2 grid + Telegram footer with QR code

- Latest News section 9 → 10 (5x2 grid for desktop balance)
- Add TelegramFooter component with QR code linking to t.me/OrangeNewsMN
- Add public/telegram_qr.png (Orange-branded QR)"
    git push
    ok "Website push дууссан. Vercel deploy эхэлсэн."
    info "Deploy status: https://vercel.com/mctunghai-1639s-projects/orangenews-website"
else
    info "Website push алгаслаа. Файлуудыг шалга: cd $TMPDIR/site"
    trap - EXIT
fi

echo
bold "🎉 БҮГД БЭЛЭН"
cat <<EOF
Hint:
  - Маргаашийн 06:00 MNT pipeline шинэ footer + QR-тай постоор ажиллана
  - Website Vercel deploy 1–2 минутын дотор live болно
  - orangenews.mn-руу ор → грид 5x2, footer-т QR харагдах ёстой
EOF
