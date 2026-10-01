#!/bin/bash
# Copy hub backups onto this machine. The hub cannot SSH in here.
set -euo pipefail
HOST="${SOZAN_HUB:-hub}"
REMOTE_DIR="${SOZAN_BACKUP_DIR:-/home/ubuntu/backups/sozan}"
DEST="${SOZAN_BACKUP_HOME_DIR:-${HOME}/backups/sozan}"
mkdir -p "$DEST"
chmod 700 "$DEST"
# No --delete: a wiped hub must not wipe this copy at the next pull. Old dirs are pruned below by age.
rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=20" \
  "${HOST}:${REMOTE_DIR}/" "${DEST}/"
chmod -R go-rwx "$DEST"
find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
count="$(find "$DEST" -mindepth 1 -maxdepth 1 -type d | wc -l)"
echo "pulled ${count} backups"
