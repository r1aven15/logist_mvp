#!/usr/bin/env python3
"""Restart local CargoHunt services if one of them stops."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {
    "web": ("/tmp/cargo-hunt-web.pid", [sys.executable, "-m", "http.server", "12000", "--bind", "0.0.0.0"], "/tmp/cargo-hunt-web.log"),
    "crm": ("/tmp/cargo-hunt-crm.pid", [sys.executable, "crm/crm_server.py", "--port", "12001", "--host", "0.0.0.0"], "/tmp/cargo-hunt-crm.log"),
    "bot": ("/tmp/cargo-hunt-bot.pid", [sys.executable, "crm/telegram_bot.py"], "/tmp/cargo-hunt-bot.log"),
    "daily": ("/tmp/cargo-hunt-daily.pid", [sys.executable, "crm/daily_scheduler.py"], "/tmp/cargo-hunt-daily.log"),
}


def alive(pid_file: str) -> bool:
    try:
        pid = int(Path(pid_file).read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, FileNotFoundError):
        return False


def start(name: str) -> None:
    pid_file, cmd, log_path = SERVICES[name]
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    Path(pid_file).write_text(str(proc.pid))
    print(f"started {name}: {proc.pid}", flush=True)


def main() -> None:
    print("CargoHunt watchdog started", flush=True)
    while True:
        for name in SERVICES:
            if not alive(SERVICES[name][0]):
                start(name)
        time.sleep(20)


if __name__ == "__main__":
    main()
