#!/bin/bash
# Nightly Sozan postgres + tenant-data backup. Keep 7 days.
set -euo pipefail
ROOT="${SOZAN_REMOTE:-/home/ubuntu/sozan-core}"
DEST_ROOT="${SOZAN_BACKUP_DIR:-/home/ubuntu/backups/sozan}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${DEST_ROOT}/${STAMP}"
mkdir -p "$DEST"
chmod 700 "$DEST_ROOT"

docker exec deploy-postgres-1 pg_dump -U sozan -d sozan_ads -Fc -f /tmp/sozan_ads.dump
docker cp deploy-postgres-1:/tmp/sozan_ads.dump "${DEST}/sozan_ads.dump"
docker exec deploy-postgres-1 rm -f /tmp/sozan_ads.dump
tar --exclude='*.pyc' --exclude='__pycache__' -C "${ROOT}/backend" -cf "${DEST}/data.tar" data
cp -a "${ROOT}/deploy/shop-upstreams.map" "${DEST}/shop-upstreams.map" 2>/dev/null || true
chmod 600 "${DEST}/sozan_ads.dump" "${DEST}/data.tar"
printf '%s\n' "$STAMP" > "${DEST}/OK"

# Drop backups older than 7 days.
find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

HOME_HOST="${SOZAN_BACKUP_HOME:-}"
if [ -n "$HOME_HOST" ]; then
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$HOME_HOST" "mkdir -p ${DEST_ROOT}" || true
  scp -o ConnectTimeout=15 -o BatchMode=yes -r "$DEST" "${HOME_HOST}:${DEST_ROOT}/" || true
fi
echo "backup ${STAMP}"
