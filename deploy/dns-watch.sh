#!/bin/bash
# Check public DNS and HTTPS for the panel, the API, and two live storefronts.
# One observe event and one log line when a failure starts, and one when it clears.
set -u
log=/home/ubuntu/sozan-bench/dns-watch.log
stamp=/home/ubuntu/sozan-bench/dns-watch.down
note=""
fail=0

check() {
  host=$1
  path=$2
  if ! dig +time=2 +tries=1 @8.8.8.8 "$host" A +noall +answer | grep -E -q '[[:space:]]A[[:space:]]'; then
    fail=1
    note="$note $host:dns"
    return
  fi
  code=$(curl --noproxy '*' -sS -o /dev/null -m 15 -w '%{http_code}' "https://$host$path" || echo 000)
  if [ "$code" != "200" ]; then
    fail=1
    note="$note $host:$code"
  fi
}

check app.sozan-core.ir /
check api.sozan-core.ir /health
check sozan.sozan-core.ir /
check gahhoeh-rasta.sozan-core.ir /

mkdir -p /home/ubuntu/sozan-bench
if [ "$fail" = 1 ]; then
  if [ ! -f "$stamp" ]; then
    date -Is > "$stamp"
    echo "$(date -Is) dns-failed$note" >> "$log"
    NOTE="$note" PYTHONPATH=/home/ubuntu/sozan-core/backend /home/ubuntu/sozan-core/backend/.venv/bin/python - << 'PY' || true
import asyncio
import os
from app.services.observe_client import emit
asyncio.run(emit(kind="dns", title="dns-failed", status="failed", surface="watch", payload={"note": os.environ.get("NOTE", "")[:240]}))
PY
  fi
  exit 1
fi
if [ -f "$stamp" ]; then
  rm -f "$stamp"
  echo "$(date -Is) dns-ok" >> "$log"
fi
exit 0
