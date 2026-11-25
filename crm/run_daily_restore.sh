#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."

while true; do
  now_hm=$(TZ=Asia/Krasnoyarsk date +%H:%M)
  today=$(TZ=Asia/Krasnoyarsk date +%F)
  last=$(cat crm/.daily_restore_last 2>/dev/null || true)
  if [[ "$now_hm" > "23:29" ]] && [ "$last" != "$today" ]; then
    echo "[supervisor] sending restore email for $today at $now_hm"
    python3 daily_restore_email.py --send >> crm/daily_restore.log 2>&1
    echo "$today" > crm/.daily_restore_last
    echo "[supervisor] restore email finished at $(TZ=Asia/Krasnoyarsk date -Is)"
  fi
  sleep 60
done
