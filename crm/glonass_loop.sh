#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
set -a
. ./.secrets/glonass.env
set +a
export GLONASS_VEHICLE_IDS="${GLONASS_VEHICLE_IDS:-505725,542782,550744,577075,621945,655079}"
export GLONASS_FUEL_TANKS="${GLONASS_FUEL_TANKS:-505725:70}"
export GLONASS_TIMEZONE="${GLONASS_TIMEZONE:-7}"
export FIREBASE_CREDENTIALS="${FIREBASE_CREDENTIALS:-.secrets/firebase-admin.json}"
while true; do
  python3 sync_glonass.py >> crm/glonass_loop.log 2>&1
  sleep 300
done
