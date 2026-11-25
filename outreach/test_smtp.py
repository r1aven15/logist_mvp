#!/usr/bin/env python3
"""Check SMTP login without sending any email."""
from pathlib import Path
from send_offer import connect_smtp, load_env


def main() -> int:
    load_env(Path(__file__).resolve().parent / ".env")
    server = connect_smtp()
    try:
        print("SMTP login OK. Письма не отправлялись.")
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
