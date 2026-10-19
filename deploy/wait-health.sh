#!/bin/bash
# Waits until a health URL answers 2xx, prints the answer, and exits 0. Exits 1 when nothing healthy answers in time.
#   wait-health.sh URL [SECONDS=40] [quiet]
# `quiet` prints nothing on success (the panel answers with a whole page).
# deploy-api.sh used to sleep 3 s and ask once; the API needs about 4 s to start, so a healthy restart looked hung and
# the fallback then killed the freshly started process.
set -u
url="${1:?usage: wait-health.sh URL [SECONDS]}"
limit="${2:-40}"
quiet="${3:-}"
end=$((SECONDS + limit))
while :; do
  if out="$(curl -fsS -m 5 "$url" 2>/dev/null)"; then
    [ "$quiet" = quiet ] || printf '%s' "$out"
    exit 0
  fi
  if [ "$SECONDS" -ge "$end" ]; then
    echo "no health from ${url} after ${limit}s" >&2
    exit 1
  fi
  sleep 1
done
