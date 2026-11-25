#!/usr/bin/env bash
# Daily lead-prep cycle. Sending is intentionally not automatic.
cd "$(dirname "$0")/.." || exit 1
python3 crm/collect.py --sources crm/sources.txt || true
python3 crm/run_mvp.py --import-candidates
python3 crm/send_queue.py --list
