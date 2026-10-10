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
git archive "$COMMIT" backend tools/qa_battery.py tools/lab_session.py deploy/sozan-worker.service deploy/sozan-battery.service deploy/sozan-battery.timer deploy/sozan-backup.sh deploy/sozan-backup.service deploy/sozan-backup.timer \
  | ssh -o ConnectTimeout=15 "$HOST" "cd ${REMOTE} && tar -x"
ssh -o ConnectTimeout=15 "$HOST" "SUITE_DIR=\$(mktemp -d /tmp/sozan-suite.XXXXXX) && cd ${REMOTE}/backend && PYTHONPATH=${REMOTE}/backend STATE_DIR=\$SUITE_DIR SOZAN_OBSERVE_OUTBOX=0 REDIS_URL=redis://127.0.0.1:1/0 LOCAL_LLM_URL=http://127.0.0.1:1/v1 .venv/bin/python -m unittest discover -s app -p '*_test.py' -q; status=\$?; rm -rf \$SUITE_DIR; exit \$status"
ssh -o ConnectTimeout=15 "$HOST" "printf '%s\n' '${LOCAL}' > ${REMOTE}/DEPLOYED_COMMIT"
REMOTE_HASH="$(ssh -o ConnectTimeout=15 "$HOST" "cat ${REMOTE}/DEPLOYED_COMMIT")"
if [ "$REMOTE_HASH" != "$LOCAL" ]; then
  echo "hash mismatch local=${LOCAL} remote=${REMOTE_HASH}" >&2
  exit 1
fi
ssh -o ConnectTimeout=15 "$HOST" "chmod +x ${REMOTE}/deploy/sozan-backup.sh && sudo cp ${REMOTE}/deploy/sozan-worker.service /etc/systemd/system/sozan-worker.service && sudo cp ${REMOTE}/deploy/sozan-battery.service /etc/systemd/system/sozan-battery.service && sudo cp ${REMOTE}/deploy/sozan-battery.timer /etc/systemd/system/sozan-battery.timer && sudo cp ${REMOTE}/deploy/sozan-backup.service /etc/systemd/system/sozan-backup.service && sudo cp ${REMOTE}/deploy/sozan-backup.timer /etc/systemd/system/sozan-backup.timer && sudo mkdir -p /etc/systemd/system/sozan-api.service.d && printf '%s\n' '[Service]' 'Environment=SOZAN_WORKER=1' | sudo tee /etc/systemd/system/sozan-api.service.d/worker.conf >/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now sozan-worker.service sozan-battery.timer sozan-backup.timer"

if ! ssh -o ConnectTimeout=15 "$HOST" "sudo systemctl restart sozan-api && sleep 3 && curl -fsS -m 8 http://127.0.0.1:8012/health"; then
  echo "restart hung; killing the listener" >&2
  ssh -o ConnectTimeout=15 "$HOST" 'pid=$(ss -ltnp | awk "/:8012/ {print}" | sed -n "s/.*pid=\\([0-9]*\\).*/\\1/p" | head -1); if [ -n "$pid" ]; then sudo kill -9 $pid; fi; sleep 1; sudo systemctl start sozan-api sozan-worker; sleep 3; curl -fsS -m 8 http://127.0.0.1:8012/health'
fi
ssh -o ConnectTimeout=15 "$HOST" "systemctl is-active sozan-api sozan-worker && curl -fsS -m 8 http://127.0.0.1:8012/health"
echo "deployed ${LOCAL}"
