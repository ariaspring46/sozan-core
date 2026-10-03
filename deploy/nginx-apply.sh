#!/bin/bash
# Put deploy/nginx-sozan-core.conf live on the hub: backup, config test BEFORE the reload, smoke test after it,
# automatic rollback to the backup when either fails. Run on the hub from a checkout of the commit to apply.
#   bash deploy/nginx-apply.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/deploy/nginx-sozan-core.conf"
LIVE="${SOZAN_NGINX_SITE:-/etc/nginx/sites-available/sozan-core}"
BAK="${LIVE}.bak-pre-apply-$(date +%s)"

for need in /var/lib/sozan-core/shop-closed.html /etc/nginx/.sozan-status-htpasswd /home/ubuntu/sozan-status; do
  [ -e "$need" ] || { echo "missing $need (the config refers to it)" >&2; exit 1; }
done

sudo cp "$LIVE" "$BAK"
echo "backup: $BAK"

rollback() {
  echo "rolling back to $BAK" >&2
  sudo cp "$BAK" "$LIVE"
  sudo nginx -t && sudo systemctl reload nginx
}

sudo cp "$SRC" "$LIVE"
if ! sudo nginx -t; then
  rollback
  echo "nginx -t failed; nothing was reloaded" >&2
  exit 1
fi
sudo systemctl reload nginx
sleep 1
if ! bash "$ROOT/tools/smoke_prod.sh" local; then
  rollback
  echo "smoke test failed after the reload; the old config is back" >&2
  exit 1
fi
echo "nginx config applied (backup kept at $BAK)"
