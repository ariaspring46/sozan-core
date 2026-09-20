#!/bin/bash
# تریگر رویدادمحور گروه تلگرام تیم سوزان.
# exit 0 = پیام جدید رسید (Z باید پردازش کند) | exit 2 = تایم‌باکس (فقط ری‌استارت)
ROOT=/home/demon/work-f/Sozan-Core
TOKEN=$(cat "$ROOT/backend/data/team-bot/token")
DEADLINE=$((SECONDS + 540))
while true; do
  OFF=$(cat "$ROOT/backend/data/team-bot/offset" 2>/dev/null || echo 127813743)
  RES=$(curl -s --max-time 70 --proxy socks5h://127.0.0.1:10801 \
    "https://api.telegram.org/bot${TOKEN}/getUpdates?offset=${OFF}&timeout=50" 2>/dev/null)
  if [ -z "$RES" ]; then
    sleep 15
    [ $SECONDS -ge $DEADLINE ] && exit 2
    continue
  fi
  COUNT=$(echo "$RES" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('result',[])))" 2>/dev/null || echo 0)
  if [ "$COUNT" -gt 0 ]; then
    echo "MESSAGE-ARRIVED: پیام جدید گروه تلگرام رسید. فوراً پردازش کن: با offset فایل backend/data/team-bot/offset آپدها را بگیر، به‌عنوان Z (ناظر کد، /home/demon/work-f/Sozan-Core) طبق قوانین talk.md پاسخ بده، offset را جلو ببر، بعد این اسکریپت را دوباره در بک‌گراند اجرا کن."
    exit 0
  fi
  [ $SECONDS -ge $DEADLINE ] && exit 2
done
