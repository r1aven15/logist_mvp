#!/usr/bin/env python3
"""Prepare or send personalized offer emails.

Default mode only writes .eml drafts to outreach/outbox/.
Sending requires --send --confirm-consent and consent=yes in the CSV row.
"""

from __future__ import annotations

import argparse
import csv
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTBOX = BASE_DIR / "outbox"
LOG_FILE = BASE_DIR / "sent.log"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONSENT_VALUES = {"yes", "y", "true", "1", "да"}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in CONSENT_VALUES


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.@-]+", "_", value, flags=re.UNICODE).strip("_")
    return cleaned[:80] or "letter"


def parse_template(path: Path) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).lstrip("\n")
    else:
        subject = "Предложение для автопарка"
        body = "\n".join(lines)
    return subject, body


def context_for(row: dict[str, str]) -> dict[str, str]:
    sender_email = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or ""
    values = {
        "company": row.get("company", "").strip() or "вашей компании",
        "contact": row.get("contact", "").strip() or "коллеги",
        "role": row.get("role", "").strip(),
        "city": row.get("city", "").strip() or "Красноярск",
        "segment": row.get("segment", "").strip(),
        "sender_name": os.getenv("SMTP_NAME", "").strip() or "Ваше имя",
        "sender_email": sender_email,
        "sender_phone": os.getenv("SENDER_PHONE", "").strip(),
        "demo_url": os.getenv("DEMO_URL", "").strip(),
        "offer_url": os.getenv("OFFER_URL", "").strip(),
    }
    values.update({key: str(value or "") for key, value in row.items()})
    return values


def render(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return values.get(key, match.group(0))
    return re.sub(r"\{\{\s*([\w-]+)\s*\}\}", replace, text)


def add_attachments(message: EmailMessage, paths: list[str]) -> None:
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            raise SystemExit(f"Attachment not found: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        if mime and mime.startswith("text/"):
            maintype, subtype = mime.split("/", 1)
        elif mime:
            maintype, subtype = mime.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )


def build_message(row: dict[str, str], subject: str, body: str, attachments: list[str]) -> EmailMessage:
    values = context_for(row)
    sender_email = values["sender_email"]
    if not sender_email:
        raise SystemExit("Set SMTP_FROM or SMTP_USER in outreach/.env")
    message = EmailMessage()
    message["From"] = formataddr((values["sender_name"], sender_email))
    message["To"] = formataddr((row.get("contact", ""), row["email"]))
    message["Reply-To"] = sender_email
    message["Subject"] = render(subject, values)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender_email.split("@", 1)[-1])
    message["List-Unsubscribe"] = f"<mailto:{sender_email}?subject=unsubscribe>"
    message.set_content(render(body, values))
    add_attachments(message, attachments)
    return message


def read_recipients(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Recipients file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            email = (row.get("email") or "").strip()
            if not email or not EMAIL_RE.match(email):
                print(f"skip invalid email: {email!r}", file=sys.stderr)
                continue
            row["email"] = email
            rows.append(row)
    return rows


def write_draft(message: EmailMessage, index: int, email: str) -> Path:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    path = OUTBOX / f"{index:03d}-{safe_name(email)}.eml"
    path.write_bytes(bytes(message))
    return path


def log_result(email: str, status: str, detail: str = "") -> None:
    exists = LOG_FILE.exists()
    with LOG_FILE.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(["timestamp", "email", "status", "detail"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), email, status, detail])


def connect_smtp() -> smtplib.SMTP:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "465"))
    mode = os.getenv("SMTP_MODE", "ssl").strip().lower()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not user or not password:
        raise SystemExit("Set SMTP_HOST, SMTP_USER and SMTP_PASSWORD in outreach/.env")
    context = ssl.create_default_context()
    if mode == "starttls":
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=context)
    else:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    server.login(user, password)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or send personalized Autopark Control emails")
    parser.add_argument("--recipients", default="outreach/recipients.csv")
    parser.add_argument("--template", default="outreach/01-first-letter.txt")
    parser.add_argument("--env", default="outreach/.env")
    parser.add_argument("--attach", action="append", default=[], help="Attachment path; can be repeated")
    parser.add_argument("--send", action="store_true", help="Actually send; default is draft only")
    parser.add_argument("--confirm-consent", action="store_true", help="Required with --send")
    parser.add_argument("--limit", type=int, default=20, help="Max emails per run (default 20)")
    parser.add_argument("--delay", type=float, default=30, help="Seconds between emails (default 30)")
    args = parser.parse_args()

    load_env(Path(args.env))
    rows = read_recipients(Path(args.recipients))
    subject, body = parse_template(Path(args.template))
    if not rows:
        raise SystemExit("No valid recipients found")

    if not args.send:
        print(f"Draft mode: {len(rows)} letters -> {OUTBOX}")
        for index, row in enumerate(rows, start=1):
            message = build_message(row, subject, body, args.attach)
            path = write_draft(message, index, row["email"])
            print(f"  draft: {path.name}")
        print("Nothing was sent. Review drafts, then use --send --confirm-consent.")
        return 0

    if not args.confirm_consent:
        raise SystemExit("Refusing to send without --confirm-consent. Use drafts first.")
    eligible = [row for row in rows if truthy(row.get("consent"))]
    if not eligible:
        raise SystemExit("No recipients with consent=yes. Add consent or send drafts manually.")
    print(f"Sending to {min(len(eligible), args.limit)} of {len(eligible)} consented recipients")
    server = connect_smtp()
    sent = 0
    try:
        for row in eligible:
            if sent >= args.limit:
                break
            message = build_message(row, subject, body, args.attach)
            try:
                server.send_message(message)
                sent += 1
                log_result(row["email"], "sent")
                print(f"  sent: {row['email']}")
            except Exception as error:  # keep going, log the failure
                log_result(row["email"], "error", str(error)[:300])
                print(f"  error: {row['email']}: {error}", file=sys.stderr)
            if sent < args.limit:
                time.sleep(max(0, args.delay))
    finally:
        try:
            server.quit()
        except Exception:
            pass
    print(f"Done. Sent: {sent}. Log: {LOG_FILE}")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
