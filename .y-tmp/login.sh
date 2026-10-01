#!/usr/bin/env bash
set -u
API="https://api.sozan-core.ir"
PHONE="09121130077"
DIR=/home/demon/work-f/Sozan-Core/.y-tmp
LOG="$DIR/login.log"
: > "$LOG"

for attempt in 1 2 3 4 5 6 7 8; do
  CH=$(curl -s "$API/auth/otp/captcha?phone=$PHONE")
  TOKEN=$(echo "$CH" | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))")
  A=$(echo "$CH" | python3 -c "
import json, sys, re
d = json.load(sys.stdin)
q = d['question'].translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
ns = [int(x) for x in re.findall(r'\d+', q)]
print(ns[0] + ns[1] if len(ns) >= 2 else '')
")
  SEND=$(curl -s -X POST "$API/auth/otp/send" -H "Content-Type: application/json" \
    -d "{\"phone\": \"$PHONE\", \"captchaToken\": \"$TOKEN\", \"captchaAnswer\": \"$A\"}")
  CODE=$(echo "$SEND" | python3 -c "import json,sys; print(json.load(sys.stdin).get('code',''))" 2>/dev/null || echo "")
  DETAIL=$(echo "$SEND" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail',''))" 2>/dev/null || echo "")
  echo "[$(date +%H:%M)] attempt $attempt: detail=$DETAIL codeLen=${#CODE}" >> "$LOG"
  if [ -n "$CODE" ]; then
    LOGIN=$(curl -s -X POST "$API/auth/otp/verify" -H "Content-Type: application/json" -d "{\"phone\": \"$PHONE\", \"code\": \"$CODE\"}")
    LEN=$(echo "$LOGIN" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('access_token','')))" 2>/dev/null || echo 0)
    echo "login token chars: $LEN" >> "$LOG"
    if [ "$LEN" -gt 50 ] 2>/dev/null; then
      echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))" > "$DIR/y-token"
      chmod 600 "$DIR/y-token"
      echo "LOGIN_OK" >> "$LOG"
      exit 0
    fi
  fi
  sleep 240
done
echo "GAVE_UP" >> "$LOG"
exit 1
