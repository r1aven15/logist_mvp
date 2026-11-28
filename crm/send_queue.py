#!/usr/bin/env python3
"""Approve and send CRM drafts with strict safety limits.

Default is a dry run. Actual sending requires both --send and --confirm.
Only rows with approved=yes are sent.
"""
from __future__ import annotations

import argparse
import csv
import imaplib
import json
import os
import re
import smtplib
import ssl
import time
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
QUEUE = BASE / "queue.csv"
LEADS = BASE / "leads.csv"
LOG = BASE / "sent.log"
FIELDS = ["id", "lead_id", "kind", "to", "subject", "draft_path", "status", "approved", "created_at", "sent_at"]


def read_queue() -> list[dict[str, str]]:
    if not QUEUE.exists():
        return []
    with QUEUE.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_queue(rows: list[dict[str, str]]) -> None:
    with QUEUE.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def mark_lead_contacted(lead_id: str) -> None:
    if not LEADS.exists():
        return
    with LEADS.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys()) if rows else []
    today = date.today().isoformat()
    for row in rows:
        if row.get("id") == lead_id:
            row["status"] = "contacted"
            row["last_contact"] = today
            row["next_action"] = "follow-up"
            row["next_date"] = (date.today() + timedelta(days=3)).isoformat()
            note = "письмо отправлено"
            if note not in row.get("notes", ""):
                row["notes"] = (row.get("notes", "").rstrip("; ") + "; " + note).strip("; ")
            break
    with LEADS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    path = ROOT / "outreach" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip())
    return env


def smtp_send(msg, env: dict[str, str]) -> None:
    host = env.get("SMTP_HOST", "smtp.mail.ru")
    port = int(env.get("SMTP_PORT", "465"))
    user = env.get("SMTP_USER", "")
    password = env.get("SMTP_PASSWORD", "")
    if not user or not password:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD не заданы")
    context = ssl.create_default_context()
    if env.get("SMTP_MODE", "ssl").lower() == "starttls":
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)


def append_sent_copy(msg, env: dict[str, str]) -> None:
    try:
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL("imap.mail.ru", 993, ssl_context=context) as imap:
            imap.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
            typ, data = imap.list()
            folder = None
            for row in data or []:
                line = row.decode("utf-8", "replace") if isinstance(row, bytes) else row
                if "\\Sent" in line:
                    match = re.search(r'"([^"]+)"\s*$', line)
                    if match:
                        folder = match.group(1)
                        break
            if folder:
                imap.append(folder, "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    except Exception as exc:
        print(f"  ! копия в «Отправленные» не сохранена: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM sender: approval + dry-run + limits")
    parser.add_argument("--list", action="store_true", help="Show queue")
    parser.add_argument("--approve", action="append", default=[], help="Queue id to approve; repeatable")
    parser.add_argument("--unapprove", action="append", default=[], help="Queue id to unapprove")
    parser.add_argument("--approve-all", action="store_true", help="Approve all drafts; requires --confirm")
    parser.add_argument("--send", action="store_true", help="Actually send approved drafts")
    parser.add_argument("--confirm", action="store_true", help="Required with --send/--approve-all")
    parser.add_argument("--limit", type=int, default=CONFIG["limits"]["max_per_day"])
    parser.add_argument("--delay", type=int, default=CONFIG["limits"]["delay_seconds"])
    args = parser.parse_args()

    rows = read_queue()
    if args.list or (not args.approve and not args.unapprove and not args.approve_all and not args.send):
        print(f"Очередь: {len(rows)}")
        for row in rows:
            print(f"{row['id']}  {row['status']:7} approved={row['approved']:3}  {row['to']:35}  {row['subject']}")
        print("\nDry-run. Для отправки: --send --confirm. Для утверждения: --approve ID.")
        return 0

    if args.approve_all and not args.confirm:
        print("--approve-all требует --confirm")
        return 2
    if args.approve_all:
        for row in rows:
            if row.get("status") == "draft":
                row["approved"] = "yes"
    for queue_id in args.approve:
        for row in rows:
            if row["id"] == queue_id:
                row["approved"] = "yes"
    for queue_id in args.unapprove:
        for row in rows:
            if row["id"] == queue_id:
                row["approved"] = "no"
    write_queue(rows)

    if not args.send:
        print("Статусы обновлены. Отправка не запускалась.")
        return 0
    if not args.confirm:
        print("Для отправки нужен --confirm")
        return 2

    env = load_env()
    today = date.today().isoformat()
    sent_today = sum(1 for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip() and today in line) if LOG.exists() else 0
    remaining = max(0, min(args.limit, CONFIG["limits"]["max_per_day"] - sent_today))
    if remaining <= 0:
        print(f"Дневной лимит исчерпан: {sent_today}/{CONFIG['limits']['max_per_day']}")
        return 0

    sent = 0
    for row in rows:
        if sent >= remaining:
            break
        if row.get("status") != "draft" or row.get("approved") != "yes":
            continue
        draft = ROOT / row["draft_path"]
        if not draft.exists():
            print(f"! нет файла: {draft}")
            continue
        msg = BytesParser(policy=policy.default).parsebytes(draft.read_bytes())
        if str(msg.get("To", "")).lower() != row["to"].lower():
            print(f"! To в письме не совпадает с очередью: {row['id']}")
            continue
        print(f"Отправка: {row['to']} — {row['subject']}")
        try:
            smtp_send(msg, env)
        except Exception as exc:
            print(f"  ! ошибка отправки: {exc}")
            row["status"] = "error"
            row["approved"] = "no"
            write_queue(rows)
            continue
        append_sent_copy(msg, env)
        mark_lead_contacted(row["lead_id"])
        row["status"] = "sent"
        row["sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": row["sent_at"], "to": row["to"], "subject": row["subject"], "message_id": msg.get("Message-ID", ""), "draft": row["draft_path"]}, ensure_ascii=False) + "\n")
        sent += 1
        write_queue(rows)
        if sent < remaining:
            time.sleep(max(0, args.delay))
    print(f"Отправлено: {sent}. Осталось на сегодня: {max(0, remaining - sent)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
