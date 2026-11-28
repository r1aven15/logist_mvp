#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."

while true; do
  echo "[supervisor] start $(date -Is)"
  python3 -u crm/max_bot.py >> crm/max_bot.log 2>&1
  code=$?
  echo "[supervisor] exit $code $(date -Is)"
  sleep 5
done
