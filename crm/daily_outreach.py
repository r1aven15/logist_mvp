#!/usr/bin/env python3
"""Daily CRM batch: refresh drafts, approve them and send up to five emails."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(*args: str) -> int:
    print("$", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily 5-email outreach")
    parser.add_argument("--send", action="store_true", help="Approve and send; without it only refresh drafts")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    today = date.today().isoformat()
    if run(PYTHON, "crm/run_mvp.py", "--today", today) != 0:
        return 1
    if not args.send:
        print("Dry run: drafts refreshed, nothing sent.")
        return 0
    if run(PYTHON, "crm/send_queue.py", "--approve-all", "--confirm") != 0:
        return 1
    return run(PYTHON, "crm/send_queue.py", "--send", "--confirm", "--limit", str(args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
