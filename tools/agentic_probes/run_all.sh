#!/usr/bin/env bash
# کاوشگرهای راستی‌آزمایی ۶ مؤلفهٔ عاملی (docs/راستی‌آزمایی-اجزای-عاملی-سوزان.md).
# هر فایل یک سناریو را با مدل/شبکهٔ ساختگی اجرا و نتیجه را چاپ می‌کند؛ تست واحد نیست و در discover نمی‌آید.
# اجرا از ریشهٔ مخزن:  bash tools/agentic_probes/run_all.sh  [python]
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${1:-python3}"
STATE="$(mktemp -d)"   # رشته‌های پس‌زمینهٔ emit_later بعد از پایان patch در همین پوشه می‌نویسند، نه backend/data
trap 'rm -rf "$STATE"' EXIT
cd "$ROOT/backend"
for probe in "$ROOT"/tools/agentic_probes/p_*.py; do
  echo "== $(basename "$probe")"
  PYTHONPATH=. STATE_DIR="$STATE" timeout 120 "$PY" "$probe" 2>&1 | grep -v '^WARNING'
done
