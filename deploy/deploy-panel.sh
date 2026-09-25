#!/bin/bash
# Deploy the seller panel from one git commit and rebuild on the hub.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMMIT="${1:-HEAD}"
HOST="${SOZAN_HUB:-hub}"
REMOTE="${SOZAN_REMOTE:-/home/ubuntu/sozan-core}"

if ! git diff --quiet -- frontend || ! git diff --cached --quiet -- frontend; then
  echo "frontend has uncommitted changes; commit them before deploy" >&2
  exit 1
fi
if ! git cat-file -e "${COMMIT}^{commit}" 2>/dev/null; then
  echo "unknown commit ${COMMIT}" >&2
  exit 1
fi

LOCAL="$(git rev-parse "$COMMIT")"
echo "deploy-panel ${LOCAL}"
git archive "$COMMIT" frontend \
  | ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE} && tar -x"
ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE}/frontend && NEXT_PUBLIC_API_URL=https://api.sozan-core.ir npm run build && sudo systemctl restart sozan-panel && sleep 2 && curl -fsS -m 8 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3010/"
echo "panel deployed ${LOCAL}"
