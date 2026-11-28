#!/usr/bin/env python3
"""Lightweight scheduler: run the daily email batch at 09:00 Krasnoyarsk (02:00 UTC)."""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    print("Daily outreach scheduler started; target 02:00 UTC.", flush=True)
    while True:
        now = datetime.now()
        if now.hour == 2 and now.minute < 5:
            subprocess.run([sys.executable, "crm/daily_outreach.py", "--send"], cwd=ROOT, check=False)
            time.sleep(3600)
        time.sleep(60)


if __name__ == "__main__":
    main()
