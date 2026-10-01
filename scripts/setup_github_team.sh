#!/usr/bin/env bash
# تنظیم تیم سه‌نفره روی github.com/Erfuni/sozan
# نیاز: gh auth login و در صورت دعوت ناظر: GH_REVIEWER=username
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.local/bin:$PATH"
REPO="${GITHUB_REPO:-Erfuni/sozan}"
OWNER="${REPO%%/*}"
NAME="${REPO#*/}"

if ! command -v gh >/dev/null; then
  echo "gh نیست. از https://cli.github.com نصب کنید یا باینری را در ~/.local/bin بگذارید."
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "وارد گیت‌هاب شوید: gh auth login"
  echo "بعد: GH_REVIEWER=<یوزرنیم-ناظر> bash scripts/setup_github_team.sh"
  exit 1
fi

reviewer="${GH_REVIEWER:-}"
if [[ -z "$reviewer" ]]; then
  echo "GH_REVIEWER خالی است. دعوت ناظر و جایگزینی CODEOWNERS رد می‌شود."
  echo "مثال: GH_REVIEWER=alice bash scripts/setup_github_team.sh"
else
  reviewer="${reviewer#@}"
  echo "دعوت ناظر @$reviewer با نقش Write"
  gh api "repos/${REPO}/collaborators/${reviewer}" -X PUT -f permission=push >/dev/null
  owners="$ROOT/.github/CODEOWNERS"
  if grep -q '@REVIEWER' "$owners"; then
    sed -i "s/@REVIEWER/@${reviewer}/" "$owners"
    echo "CODEOWNERS → @${reviewer}"
  fi
fi

echo "لیبل‌ها"
for spec in "shop|فروشگاه|C4A574" "studio|استودیو|8B5A2B" "inbox|صندوق|5C3A21" "infra|زیرساخت|6B7280"; do
  IFS='|' read -r label desc color <<<"$spec"
  gh label create "$label" --repo "$REPO" --description "$desc" --color "$color" 2>/dev/null \
    || gh label edit "$label" --repo "$REPO" --description "$desc" --color "$color"
done

echo "ruleset روی main"
payload='{
  "name": "main-three-person",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    }
  ]
}'
existing="$(gh api "repos/${REPO}/rulesets" --jq '.[] | select(.name=="main-three-person") | .id' 2>/dev/null || true)"
if [[ -n "$existing" ]]; then
  echo "$payload" | gh api "repos/${REPO}/rulesets/${existing}" -X PUT --input -
else
  echo "$payload" | gh api "repos/${REPO}/rulesets" -X POST --input -
fi

echo "Project چهارستونه"
project_number="$(gh project list --owner "$OWNER" --format json --jq '.projects[] | select(.title=="سوزان") | .number' 2>/dev/null | head -1 || true)"
if [[ -z "$project_number" ]]; then
  project_number="$(gh project create --owner "$OWNER" --title "سوزان" --format json --jq '.number')"
fi
echo "پروژه سوزان #${project_number} — ستون‌های وضعیت را در UI به Backlog / Doing / Review / Done برسانید."
echo "https://github.com/users/${OWNER}/projects/${project_number}"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "docs/github-three-person" ]]; then
  echo "پوش برنچ فرآیند (نه main)"
  git push -u origin docs/github-three-person
  if ! gh pr view --repo "$REPO" >/dev/null 2>&1; then
    gh pr create --repo "$REPO" --base main --head docs/github-three-person \
      --title "جریان گیت‌هاب سه‌نفره" \
      --body "$(cat <<'EOF'
## خلاصه
قالب Issue/PR، CODEOWNERS، CHANGELOG و سند جریان تیم. کد اپ در این PR نیست.

## چرا
سه نقش: مالک اولویت می‌دهد، برنامه‌نویس PR می‌گذارد، فقط ناظر merge می‌کند.

## فایل‌های اصلی
- `.github/CODEOWNERS`
- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/task.md`
- `CHANGELOG.md`
- `docs/جریان-گیت‌هاب.md`
- `scripts/setup_github_team.sh`

## تست
- [x] فقط فایل جریان است؛ تغییرات فروشگاه/استودیو جدا می‌ماند

## ریسک
هیچ برای محصول زنده. ruleset را مالک با همین اسکریپت یا Settings می‌زند.

## تغییرات این مرحله
- جریان گیت‌هاب سه‌نفره با ناظر اجباری

## ادغام
- [ ] ناظر ریویو خط‌به‌خط کرده
- [x] **فقط ناظر merge می‌کند**
EOF
)"
  fi
  if [[ -n "$reviewer" ]]; then
    gh pr edit --repo "$REPO" --add-reviewer "$reviewer" || true
  fi
  gh pr view --repo "$REPO" --json url --jq .url
fi

echo "تمام. به main پوش نشد."
