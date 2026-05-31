#!/usr/bin/env bash
# =============================================================================
# Orange News website (orangenews.mn) — "Latest News" 9 → 10 (5x2 grid)
# =============================================================================
# Ажиллах: bash setup_website_grid.sh
#
# Хийдэг зүйл:
#   1. gh CLI-аар таны GitHub-ын Orange News website repo-г олно
#   2. Түр хавтсанд clone хийнэ
#   3. "Latest News" гэж нэрлэгдсэн component-ийг grep-ээр олно
#   4. slice(0, 9) → slice(0, 10), grid-cols-3 → grid-cols-5 болгож засна
#   5. Diff-ийг танд харуулж, push-ийг зөвшөөрвөл commit + push (Vercel autodeploy)
# =============================================================================

set -euo pipefail

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✅ %s\033[0m\n" "$1"; }
err()  { printf "\033[31m❌ %s\033[0m\n" "$1" >&2; }
warn() { printf "\033[33m⚠️  %s\033[0m\n" "$1"; }
info() { printf "\033[36mℹ️  %s\033[0m\n" "$1"; }

for cmd in gh git jq; do
    command -v "$cmd" >/dev/null 2>&1 || { err "$cmd хэрэгтэй: brew install $cmd"; exit 1; }
done

gh auth status >/dev/null 2>&1 || gh auth login

echo
bold "🍊 Orange News website 9→10 grid update"
echo "========================================"
echo

# -----------------------------------------------------------------------------
# 1. Repo олох
# -----------------------------------------------------------------------------
bold "Алхам 1/4 — Website repo олох"
USER=$(gh api user --jq .login)
info "GitHub user: $USER"

echo "Тохирох repo нэрсүүд (Next.js, орангэ үг агуулсан):"
CANDIDATES=$(gh repo list "$USER" --limit 100 --json name,description,url,defaultBranchRef \
    --jq '.[] | select(.name | test("(?i)orange|news|web|site")) | "\(.name) | \(.url)"')

if [[ -z "$CANDIDATES" ]]; then
    err "Orange News website repo олдсонгүй. Гар аргаар repo-ийн нэр оруулна уу:"
    read -rp "Repo нэр (жишээ нь orange-news-web): " REPO_NAME
else
    echo "$CANDIDATES" | nl
    read -rp "Аль нь website (Vercel deploy) repo вэ? Дугаараар сонго: " IDX
    REPO_NAME=$(echo "$CANDIDATES" | sed -n "${IDX}p" | awk -F' \\| ' '{print $1}')
fi

REPO_FULL="$USER/$REPO_NAME"
ok "Сонгосон repo: $REPO_FULL"
echo

# -----------------------------------------------------------------------------
# 2. Clone & search
# -----------------------------------------------------------------------------
bold "Алхам 2/4 — Repo clone + 'Latest News' хэсгийг хайх"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
gh repo clone "$REPO_FULL" "$TMPDIR/repo" -- --depth=1 --quiet
cd "$TMPDIR/repo"

# "Сүүлийн үеийн" / "Latest" гэх хайлт
HITS=$(grep -rEln \
    --include="*.tsx" --include="*.jsx" --include="*.ts" --include="*.js" --include="*.astro" --include="*.vue" \
    -e "Сүүлийн үеийн" -e "Latest News" -e "latestNews" -e "latest_news" -e "LatestNews" \
    -e "slice\(0, ?9\)" -e "take\(9\)" -e "limit: ?9" \
    . 2>/dev/null || true)

if [[ -z "$HITS" ]]; then
    warn "'Latest News' / slice(0,9) hits олдсонгүй"
    info "Grid-cols-3 ашигладаг файлуудыг шалга:"
    grep -rEln --include="*.tsx" --include="*.jsx" "grid-cols-3" . | head -10
    read -rp "Файлын зам бичнэ үү (relative to repo root): " TARGET_FILE
else
    echo "$HITS" | nl
    read -rp "Аль файл вэ? Дугаараар сонго (эсвэл Enter — эхнийх): " IDX
    if [[ -z "$IDX" ]]; then
        TARGET_FILE=$(echo "$HITS" | head -1)
    else
        TARGET_FILE=$(echo "$HITS" | sed -n "${IDX}p")
    fi
fi

[[ -f "$TARGET_FILE" ]] || { err "Файл олдсонгүй: $TARGET_FILE"; exit 1; }
ok "Зорилтот файл: $TARGET_FILE"
echo

# -----------------------------------------------------------------------------
# 3. Auto-edit
# -----------------------------------------------------------------------------
bold "Алхам 3/4 — Файл засвар"
cp "$TARGET_FILE" "$TARGET_FILE.bak"

# Засварлах хэв шинж:
#   slice(0, 9)         -> slice(0, 10)
#   take(9)             -> take(10)
#   limit: 9            -> limit: 10
#   grid-cols-3         -> grid-cols-5 (МӨН lg:grid-cols-3 → lg:grid-cols-5)
python3 - "$TARGET_FILE" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
orig = s

s = re.sub(r"\.slice\(\s*0\s*,\s*9\s*\)", ".slice(0, 10)", s)
s = re.sub(r"\.take\(\s*9\s*\)",          ".take(10)",     s)
s = re.sub(r"limit:\s*9\b",               "limit: 10",     s)
s = re.sub(r"LATEST_NEWS_LIMIT\s*=\s*9",  "LATEST_NEWS_LIMIT = 10", s)

# Tailwind grid: 3 баганаас 5 болгох (lg: prefix хадгална)
s = re.sub(r"(\b(?:lg:|md:|sm:|xl:|2xl:)?)grid-cols-3\b", r"\1grid-cols-5", s)

if s == orig:
    print("⚠️  Pattern таарсангүй — гар аргаар засах хэрэгтэй")
    sys.exit(0)

p.write_text(s, encoding="utf-8")
print("✅ Засагдсан pattern-үүд:")
for pat in ["slice(0, 10)", "take(10)", "limit: 10", "LATEST_NEWS_LIMIT = 10", "grid-cols-5"]:
    if pat in s and pat not in orig:
        print(f"   • {pat}")
PY

echo
info "Diff:"
diff -u "$TARGET_FILE.bak" "$TARGET_FILE" || true
rm "$TARGET_FILE.bak"
echo

# -----------------------------------------------------------------------------
# 4. Commit + push
# -----------------------------------------------------------------------------
bold "Алхам 4/4 — Commit + push"
read -rp "Энэ өөрчлөлтийг push хийх үү? (Vercel автомат deploy хийнэ) [y/N]: " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    git config user.email "$(gh api user --jq .email // 'mc.tunghai@gmail.com')"
    git config user.name "$USER"
    git add "$TARGET_FILE"
    git commit -m "feat(home): Latest News 9 → 10 (5x2 grid for desktop balance)"
    git push
    ok "Push хийгдлээ. Vercel deploy эхэлсэн."
    info "Deploy status: https://vercel.com/dashboard"
else
    info "Push алгаслаа. Файлыг шалгахдаа: cd $TMPDIR/repo"
    trap - EXIT  # don't auto-delete tmpdir
fi
