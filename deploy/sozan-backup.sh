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
set +e
tar --exclude='*.pyc' --exclude='__pycache__' -C "${ROOT}/backend" -cf "${DEST}/data.tar" data
tar_status=$?
set -e
if [ "$tar_status" -gt 1 ]; then
  exit "$tar_status"
fi
cp -a "${ROOT}/deploy/shop-upstreams.map" "${DEST}/shop-upstreams.map" 2>/dev/null || true
chmod 700 "$DEST"
chmod 600 "${DEST}/sozan_ads.dump" "${DEST}/data.tar"
printf '%s\n' "$STAMP" > "${DEST}/OK"

# Drop backups older than 7 days.
find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

# Optional push when the home machine accepts SSH. This workstation does not;
# it pulls with deploy/sozan-backup-pull.sh instead.
HOME_HOST="${SOZAN_BACKUP_HOME:-}"
HOME_DIR="${SOZAN_BACKUP_HOME_DIR:-backups/sozan}"
if [ -n "$HOME_HOST" ]; then
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$HOME_HOST" "mkdir -p \"\$HOME/${HOME_DIR}\" && chmod 700 \"\$HOME/${HOME_DIR}\"" || true
  scp -o ConnectTimeout=15 -o BatchMode=yes -r "$DEST" "${HOME_HOST}:${HOME_DIR}/" || true
fi
echo "backup ${STAMP}"
