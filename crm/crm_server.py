#!/usr/bin/env python3
"""Private CargoHunt CRM: static UI + lead API with HTTP Basic auth."""
from __future__ import annotations

import argparse
import base64
import csv
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
LEADS = BASE / "leads.csv"
TG_LEADS = BASE / "telegram_leads.csv"
UI = BASE / "crm.html"
STATUSES = {"new", "contacted", "replied", "won", "lost"}


def load_env() -> None:
    env = BASE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()


load_env()
CRM_USER = os.getenv("CRM_USER", "admin")
CRM_PASSWORD = os.getenv("CRM_PASSWORD", "")
if not CRM_PASSWORD:
    raise SystemExit("CRM_PASSWORD не задан в crm/.env")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def lead_rows() -> list[dict[str, str]]:
    rows = read_rows(LEADS)
    tg = read_rows(TG_LEADS)
    by_phone = {}
    for item in tg:
        digits = "".join(ch for ch in item.get("phone", "") if ch.isdigit())
        if digits:
            by_phone[digits] = item
    for row in rows:
        if row.get("source") in {"сайт", "карточка организации"}:
            row["source"] = "Сайт"
        digits = "".join(ch for ch in row.get("phone", "") if ch.isdigit())
        extra = by_phone.get(digits)
        if extra:
            row["chat_id"] = extra.get("chat_id", "")
            row["username"] = extra.get("username", "")
            row["fleet"] = extra.get("fleet", "")
            row["created_at"] = extra.get("created_at", "")
    rows.sort(key=lambda x: (x.get("source") != "Telegram", x.get("company", "").lower()))
    return rows


class Handler(BaseHTTPRequestHandler):
    server_version = "CargoHuntCRM/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, password = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
        except Exception:
            return False
        return hmac.compare_digest(user, CRM_USER) and hmac.compare_digest(password, CRM_PASSWORD)

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CargoHunt CRM"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Требуется пароль CRM".encode("utf-8"))
        return False

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"ok": True})
            return
        if not self.require_auth():
            return
        if path in {"/", "/crm.html"}:
            data = UI.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/leads":
            self.send_json({"leads": lead_rows()})
            return
        self.send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self.require_auth():
            return
        if urlparse(self.path).path != "/api/update":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "bad json"}, 400)
            return
        lead_id = str(payload.get("id", ""))
        status = str(payload.get("status", ""))
        notes = str(payload.get("notes", ""))[:2000]
        if status not in STATUSES:
            self.send_json({"error": "bad status"}, 400)
            return
        rows = read_rows(LEADS)
        fields = list(rows[0].keys()) if rows else []
        found = False
        for row in rows:
            if row.get("id") == lead_id:
                row["status"] = status
                row["notes"] = notes
                found = True
                break
        if not found:
            self.send_json({"error": "lead not found"}, 404)
            return
        write_rows(LEADS, fields, rows)
        self.send_json({"ok": True, "id": lead_id, "status": status})


def main() -> int:
    parser = argparse.ArgumentParser(description="CargoHunt CRM server")
    parser.add_argument("--port", type=int, default=12001)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CRM on http://{args.host}:{args.port} (user={CRM_USER})")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
