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
git archive "$COMMIT" frontend deploy/wait-health.sh \
  | ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE} && tar -x"
# The panel takes 5-10 s to answer after a restart (measured: ready in 4.5 s, first page 9.4 s): wait for it instead of asking once after 2 s.
ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE}/frontend && NEXT_PUBLIC_API_URL=https://api.sozan-core.ir npm run build && sudo systemctl restart sozan-panel && bash ${REMOTE}/deploy/wait-health.sh http://127.0.0.1:3010/ 90 quiet && echo 'panel answered'"
echo "panel deployed ${LOCAL}"
