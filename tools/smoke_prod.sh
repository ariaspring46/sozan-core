#!/usr/bin/env bash
# Read-only smoke test of a running Sozan hub. Nothing is written, no login is used.
#   tools/smoke_prod.sh local    # on the hub: nginx on 127.0.0.1:80 with Host headers (also checks the response headers)
#   tools/smoke_prod.sh public   # from anywhere: through the CDN over https
# SMOKE_SHOP=<host> picks the live shop to look at (default azmaish-panl.sozan-core.ir).
set -uo pipefail
MODE="${1:-local}"
SHOP="${SMOKE_SHOP:-azmaish-panl.sozan-core.ir}"
fail=0

ok() { printf 'OK   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=$((fail + 1)); }

fetch() { # host path -> prints "<code>\n<headers>" ; body to $BODY
  local host="$1" path="$2"
  if [ "$MODE" = "local" ]; then
    curl -s -m 15 -D "$HDR" -o "$BODY" -w '%{http_code}' -H "Host: $host" "http://127.0.0.1:80$path"
  else
    curl -s -m 15 -D "$HDR" -o "$BODY" -w '%{http_code}' "https://$host$path"
  fi
}
HDR="$(mktemp)"; BODY="$(mktemp)"; trap 'rm -f "$HDR" "$BODY"' EXIT
header() { grep -i "^$1:" "$HDR" | tr -d '\r' | head -1 | cut -d: -f2- | sed 's/^ *//'; }

check_code() { # label host path expected-regex
  local code; code="$(fetch "$2" "$3")"
  if [[ "$code" =~ ^($4)$ ]]; then ok "$1 -> $code"; else bad "$1 -> $code (wanted $4)"; fi
}

check_code "landing" sozan-core.ir / 200
check_code "panel login" app.sozan-core.ir /login 200
check_code "api health" api.sozan-core.ir /health 200
grep -q '"ok":true' "$BODY" && ok "api health body ok" || bad "api health body has no ok:true"
check_code "live shop" "$SHOP" / 200
check_code "beacon on the shop host" "$SHOP" /sozan-preview-beacon.js 200
grep -qi "javascript" "$HDR" && ok "beacon is javascript" || bad "beacon content-type is not javascript"
[ "$(wc -c <"$BODY")" -gt 5000 ] && ok "beacon body present" || bad "beacon body too small"
check_code "panel is not an open API" api.sozan-core.ir /shop 401

# the CDN must serve the beacon file that is on the hub, at the very URL the shop page injects (stale CDN copy = old editor behaviour)
BEACON_FILE="${SMOKE_BEACON_FILE:-/var/lib/sozan-core/sozan-preview-beacon.js}"
if [ "$MODE" = "public" ] && [ -f "$BEACON_FILE" ]; then
  fetch "$SHOP" / >/dev/null
  url="$(grep -o '/sozan-preview-beacon.js?v=[A-Za-z0-9._-]*' "$BODY" | head -1)"
  if [ -z "$url" ]; then
    bad "the shop page does not inject the beacon"
  else
    served="$(curl -s -m 15 "https://$SHOP$url" | sha256sum | cut -d' ' -f1)"
    mine="$(sha256sum "$BEACON_FILE" | cut -d' ' -f1)"
    [ "$served" = "$mine" ] && ok "CDN serves the deployed beacon ($url)" || bad "CDN serves an OLD beacon at $url: bump v= in deploy/nginx-sozan-core.conf and run deploy/nginx-apply.sh"
  fi
fi

if [ "$MODE" = "local" ]; then
  check_code "unknown shop host" nosuchshop.sozan-core.ir / "404|503"
  fetch app.sozan-core.ir /login >/dev/null
  [ "$(header x-frame-options)" = "DENY" ] && ok "panel is not frameable" || bad "panel has no X-Frame-Options: DENY (nginx file not applied?)"
  [ "$(header x-content-type-options)" = "nosniff" ] && ok "panel nosniff" || bad "panel has no nosniff"
  fetch "$SHOP" / >/dev/null
  [ -z "$(header x-frame-options)" ] && ok "shop stays frameable for the panel preview" || bad "shop sends X-Frame-Options: the panel preview would break"
  [ "$(header x-content-type-options)" = "nosniff" ] && ok "shop nosniff" || bad "shop has no nosniff"
  fetch "$SHOP" / >/dev/null
  grep -q "sozan-preview-beacon.js" "$BODY" && ok "beacon injected into the shop page" || bad "beacon is not injected (sub_filter)"
fi

[ "$fail" -eq 0 ] && echo "smoke $MODE: all ok" || echo "smoke $MODE: $fail failed"
exit "$fail"
