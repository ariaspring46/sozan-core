#!/bin/bash
# Deploy backend from one git commit. Dirty frontend files and voice-gateway stay put.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMMIT="${1:-HEAD}"
HOST="${SOZAN_HUB:-hub}"
REMOTE="${SOZAN_REMOTE:-/home/ubuntu/sozan-core}"

if ! git diff --quiet -- backend || ! git diff --cached --quiet -- backend; then
  echo "backend has uncommitted changes; commit them before deploy" >&2
  exit 1
fi
if ! git cat-file -e "${COMMIT}^{commit}" 2>/dev/null; then
  echo "unknown commit ${COMMIT}" >&2
  exit 1
fi

LOCAL="$(git rev-parse "$COMMIT")"
echo "deploy ${LOCAL}"
git archive "$COMMIT" backend tools/qa_battery.py deploy/sozan-worker.service deploy/sozan-battery.service deploy/sozan-battery.timer \
  | ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE} && tar -x"
ssh -o ConnectTimeout=15 "$HOST" "printf '%s\n' '${LOCAL}' > ${REMOTE}/DEPLOYED_COMMIT"
REMOTE_HASH="$(ssh -o ConnectTimeout=15 "$HOST" "cat ${REMOTE}/DEPLOYED_COMMIT")"
if [ "$REMOTE_HASH" != "$LOCAL" ]; then
  echo "hash mismatch local=${LOCAL} remote=${REMOTE_HASH}" >&2
  exit 1
fi

ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE}/backend && .venv/bin/python -m unittest app.services.tenant_lock_test app.services.turn_parse_test app.services.router_service_test app.services.studio_chat_service_test app.services.studio_compose_service_test"
ssh -o ConnectTimeout=15 "$HOST" "sudo cp ${REMOTE}/deploy/sozan-worker.service /etc/systemd/system/sozan-worker.service && sudo cp ${REMOTE}/deploy/sozan-battery.service /etc/systemd/system/sozan-battery.service && sudo cp ${REMOTE}/deploy/sozan-battery.timer /etc/systemd/system/sozan-battery.timer && sudo mkdir -p /etc/systemd/system/sozan-api.service.d && printf '%s\n' '[Service]' 'Environment=SOZAN_WORKER=1' | sudo tee /etc/systemd/system/sozan-api.service.d/worker.conf >/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now sozan-worker.service sozan-battery.timer"

if ! ssh -o ConnectTimeout=15 "$HOST" "sudo systemctl restart sozan-api && sleep 3 && curl -fsS -m 8 http://127.0.0.1:8012/health"; then
  echo "restart hung; killing the listener" >&2
  ssh -o ConnectTimeout=15 "$HOST" 'pid=$(ss -ltnp | awk "/:8012/ {print}" | sed -n "s/.*pid=\\([0-9]*\\).*/\\1/p" | head -1); if [ -n "$pid" ]; then sudo kill -9 $pid; fi; sleep 1; sudo systemctl start sozan-api; sleep 3; curl -fsS -m 8 http://127.0.0.1:8012/health'
fi
ssh -o ConnectTimeout=15 "$HOST" "systemctl is-active sozan-api sozan-worker && curl -fsS -m 8 http://127.0.0.1:8012/health"
echo "deployed ${LOCAL}"
