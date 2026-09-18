#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/ubuntu/sozan-core
cd "$ROOT"
chmod 600 "$ROOT/.env" 2>/dev/null || true
install -m 644 "$ROOT/frontend/public/sozan-preview-beacon.js" /tmp/sozan-preview-beacon.js
sudo mkdir -p /var/lib/sozan-core
sudo cp /tmp/sozan-preview-beacon.js /var/lib/sozan-core/sozan-preview-beacon.js
sudo chmod 644 /var/lib/sozan-core/sozan-preview-beacon.js
: > /tmp/2326207.txt
sudo cp /tmp/2326207.txt /var/lib/sozan-core/2326207.txt
sudo chmod 644 /var/lib/sozan-core/2326207.txt
install -m 644 "$ROOT/deploy/nginx-sozan-core.conf" /tmp/sozan-core.nginx
sudo cp /tmp/sozan-core.nginx /etc/nginx/sites-available/sozan-core
sudo ln -sfn /etc/nginx/sites-available/sozan-core /etc/nginx/sites-enabled/sozan-core
sudo nginx -t
sudo systemctl reload nginx

docker compose -f "$ROOT/deploy/docker-compose.yml" up -d
for i in $(seq 1 30); do
  if python3 - <<'PY'
import socket
s=socket.socket(); s.settimeout(1)
try:
    s.connect(("127.0.0.1", 15432)); s.close(); raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
  then break
  fi
  sleep 1
done

python3 -m venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/pip" install -q -U pip \
  --default-timeout=60 \
  -i https://mirror-pypi.runflare.com/simple \
  --trusted-host mirror-pypi.runflare.com
"$ROOT/backend/.venv/bin/pip" install -q \
  --default-timeout=60 \
  -i https://mirror-pypi.runflare.com/simple \
  --trusted-host mirror-pypi.runflare.com \
  -r "$ROOT/backend/requirements.txt"

cd "$ROOT/frontend"
npm install --no-audit --no-fund --registry https://mirror-npm.runflare.com
NEXT_PUBLIC_API_URL=https://api.sozan-core.ir npm run build

sudo cp "$ROOT/deploy/sozan-api.service" /etc/systemd/system/sozan-api.service
sudo cp "$ROOT/deploy/sozan-panel.service" /etc/systemd/system/sozan-panel.service
sudo systemctl daemon-reload
sudo systemctl enable --now sozan-api.service
sudo systemctl enable --now sozan-panel.service
sudo systemctl restart sozan-api sozan-panel
sleep 2
sudo systemctl --no-pager --full status sozan-api sozan-panel | sed -n '1,80p'
