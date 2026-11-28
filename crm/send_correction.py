#!/usr/bin/env python3
"""Send a one-off correction email with stable links to earlier recipients."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(BASE))
from send_queue import append_sent_copy, load_env, smtp_send  # noqa: E402

RECIPIENTS = [
    ("continentaltruck@bk.ru", "Continental truck"),
    ("office@virteg.ru", "Виртэг"),
    ("pecom@pecom.ru", "ПЭК"),
    ("info@trasko.ru", "Траско"),
    ("contact@r-trans.ru", "Р-Транс Логистика"),
]


def build_message(config: dict, to: str, company: str) -> EmailMessage:
    links = config["links"]
    sender = config["sender"]
    body = f"""Здравствуйте, коллеги!

Ранее я отправлял вам презентацию «Автопарк Контроль». На временном демо-сервере произошёл сбой, поэтому ссылки могли не открыться. Извините за неудобство.

Постоянные ссылки:
Презентация: {links['presentation']}
Демо: {links['demo']}
PDF: {links['pdf']}

Если удобно, покажу 10 минут на вашем примере. Если не актуально — просто ответьте «нет», больше не напишу.

С уважением,
{sender['name']}
{sender['phone']}
{sender['email']}

{config.get('disclosure', '')}
"""
    msg = EmailMessage()
    msg["From"] = f"{sender['name']} <{sender['email']}>"
    msg["To"] = to
    msg["Subject"] = "Автопарк Контроль — исправленные ссылки"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="mail.ru")
    msg.set_content(body)
    return msg


def mark_lead(email: str) -> None:
    path = BASE / "leads.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys()) if rows else []
    today = date.today().isoformat()
    for row in rows:
        if row.get("email", "").lower() == email.lower():
            row["status"] = "contacted"
            row["last_contact"] = today
            row["next_action"] = "follow-up"
            row["next_date"] = (date.today() + timedelta(days=3)).isoformat()
            note = "отправлено письмо-исправление со ссылками GitHub Pages"
            if note not in row.get("notes", ""):
                row["notes"] = (row.get("notes", "").rstrip("; ") + "; " + note).strip("; ")
            break
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send correction emails with stable links")
    parser.add_argument("--send", action="store_true", help="Actually send; default is dry run")
    parser.add_argument("--delay", type=int, default=2)
    args = parser.parse_args()
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    env = load_env()
    sent = 0
    for to, company in RECIPIENTS:
        msg = build_message(config, to, company)
        draft = BASE / "outbox" / f"correction-{to.split('@')[0]}-{date.today().isoformat()}.eml"
        draft.write_bytes(msg.as_bytes())
        print(f"{'Отправка' if args.send else 'Черновик'}: {to} — {msg['Subject']}")
        if not args.send:
            continue
        try:
            smtp_send(msg, env)
        except Exception as exc:
            print(f"  ! ошибка: {exc}")
            continue
        append_sent_copy(msg, env)
        mark_lead(to)
        with (BASE / "sent.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "to": to, "subject": msg["Subject"], "message_id": msg["Message-ID"], "kind": "correction"}, ensure_ascii=False) + "\n")
        sent += 1
        if args.delay:
            time.sleep(args.delay)
    print(f"Отправлено: {sent}/{len(RECIPIENTS)}")
    return 0 if sent == len(RECIPIENTS) or not args.send else 1


if __name__ == "__main__":
    raise SystemExit(main())
