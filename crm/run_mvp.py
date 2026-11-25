#!/usr/bin/env python3
"""Generate personalized drafts, queue and CRM dashboard from leads.csv."""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import uuid
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
LEADS = BASE / "leads.csv"
QUEUE = BASE / "queue.csv"
OUTBOX = BASE / "outbox"
DASHBOARD = BASE / "dashboard.html"
FIELDS = ["id", "company", "segment", "city", "website", "email", "phone", "contact", "role", "source", "basis", "status", "score", "last_contact", "next_action", "next_date", "notes", "source_id"]
QUEUE_FIELDS = ["id", "lead_id", "kind", "to", "subject", "draft_path", "status", "approved", "created_at", "sent_at"]


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def score(lead: dict[str, str]) -> int:
    value = 0
    value += 25 if lead.get("email") else 0
    value += 15 if lead.get("website") else 0
    value += 10 if lead.get("phone") else 0
    value += 10 if lead.get("contact") else 0
    value += 10 if "директор" in lead.get("role", "").lower() else 0
    value += 10 if lead.get("city") else 0
    value += 10 if any(x in lead.get("segment", "").lower() for x in ("перевоз", "логист", "автовоз", "груз", "транспорт")) else 0
    value += 5 if lead.get("website") and lead.get("email") else 0
    return min(100, value)


def greeting(lead: dict[str, str]) -> str:
    contact = (lead.get("contact") or "").strip()
    if contact and contact.lower() not in {"общий адрес", "коллеги"}:
        return contact
    return "коллеги"


def render(template: str, lead: dict[str, str]) -> tuple[str, str]:
    values = {
        **CONFIG["sender"],
        **CONFIG["links"],
        "company": lead.get("company", ""),
        "greeting": greeting(lead),
        "disclosure": CONFIG["disclosure"],
        "sender_name": CONFIG["sender"]["name"],
        "first_name": CONFIG["sender"]["first_name"],
        "city_from": CONFIG["sender"]["city_from"],
        "phone": CONFIG["sender"]["phone"],
        "email": CONFIG["sender"]["email"],
        "city": CONFIG["sender"]["city"],
    }
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    lines = text.splitlines()
    subject = lines[0].removeprefix("Тема:").strip() if lines and lines[0].startswith("Тема:") else "Автопарк Контроль"
    body = "\n".join(lines[1:]).lstrip("\n")
    return subject, body


def build_message(lead: dict[str, str], kind: str) -> EmailMessage:
    template_path = BASE / "templates" / ("follow_up.txt" if kind == "follow_up" else "first_email.txt")
    subject, body = render(template_path.read_text(encoding="utf-8"), lead)
    if kind == "follow_up":
        subject = "Re: " + subject
    msg = EmailMessage()
    msg["From"] = f"{CONFIG['sender']['name']} <{CONFIG['sender']['email']}>"
    msg["To"] = lead["email"]
    msg["Reply-To"] = CONFIG["sender"]["email"]
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="mail.ru")
    msg["X-CRM-Lead"] = lead["id"]
    msg["X-CRM-Kind"] = kind
    msg.set_content(body)
    attachment = ROOT / CONFIG["attachment"]
    if attachment.exists():
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename="autopark-control-presentation.pdf")
    return msg


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM MVP: drafts, queue and dashboard")
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--draft-all", action="store_true", help="Generate drafts for contacted leads too (testing)")
    parser.add_argument("--force", action="store_true", help="Replace existing drafts for the same lead/kind")
    parser.add_argument("--import-candidates", action="store_true", help="Add crm/candidates.csv to leads.csv")
    args = parser.parse_args()

    OUTBOX.mkdir(exist_ok=True)
    leads = read_csv(LEADS, FIELDS)
    queue = read_csv(QUEUE, QUEUE_FIELDS)

    if args.import_candidates:
        candidates = read_csv(BASE / "candidates.csv", ["company", "email", "phone", "source", "title", "notes"])
        existing = {x.get("email", "").lower() for x in leads}
        for item in candidates:
            email = item.get("email", "").strip()
            if not email or email.lower() in existing:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", (item.get("company") or email).lower()).strip("-")[:40] or uuid.uuid4().hex[:8]
            leads.append({
                "id": slug + "-" + uuid.uuid4().hex[:4],
                "company": item.get("company") or email,
                "segment": "", "city": "Красноярск", "website": item.get("source", ""),
                "email": email, "phone": item.get("phone", ""), "contact": "", "role": "",
                "source": item.get("source", ""), "basis": "public_business", "status": "new",
                "score": "", "last_contact": "", "next_action": "first_email", "next_date": args.today,
                "notes": item.get("notes", ""),
            })
            existing.add(email.lower())
        print(f"Импортировано кандидатов: {len(leads)} всего")

    for lead in leads:
        lead["score"] = str(score(lead))

    existing_keys = {(q["lead_id"], q["kind"]) for q in queue if q.get("status") not in {"cancelled"}}
    created = 0
    for lead in leads:
        if not lead.get("email") or lead.get("basis") not in {"public_business", "consent"}:
            continue
        due_followup = lead.get("status") == "contacted" and lead.get("next_date") and lead["next_date"] <= args.today and lead.get("next_action") in {"follow-up", "follow_up"}
        new_lead = lead.get("status") == "new"
        if not (new_lead or due_followup or (args.draft_all and lead.get("status") == "contacted")):
            continue
        kind = "first_email" if new_lead and not args.draft_all else "follow_up"
        key = (lead["id"], kind)
        if key in existing_keys and not args.force:
            continue
        if args.force:
            queue = [q for q in queue if (q.get("lead_id"), q.get("kind")) != key]
        msg = build_message(lead, kind)
        queue_id = uuid.uuid4().hex[:10]
        draft_path = OUTBOX / f"{queue_id}-{lead['id']}-{kind}.eml"
        draft_path.write_bytes(msg.as_bytes())
        queue.append({
            "id": queue_id, "lead_id": lead["id"], "kind": kind, "to": lead["email"],
            "subject": msg["Subject"], "draft_path": str(draft_path.relative_to(ROOT)),
            "status": "draft", "approved": "no", "created_at": datetime.now().isoformat(timespec="seconds"), "sent_at": "",
        })
        existing_keys.add(key)
        created += 1
        print(f"Черновик: {lead['company']} <{lead['email']}> — {msg['Subject']}")

    write_csv(LEADS, FIELDS, leads)
    write_csv(QUEUE, QUEUE_FIELDS, queue)

    # Dashboard
    total = len(leads)
    by_status = {}
    for lead in leads:
        by_status[lead.get("status", "")] = by_status.get(lead.get("status", ""), 0) + 1
    due = sum(1 for x in leads if x.get("next_date") and x["next_date"] <= args.today and x.get("status") == "contacted")
    draft_count = sum(1 for x in queue if x.get("status") == "draft")
    rows = []
    for lead in sorted(leads, key=lambda x: (-int(x.get("score") or 0), x.get("company", ""))):
        status = lead.get("status", "")
        rows.append(f"""<tr>
<td><b>{html.escape(lead.get('company',''))}</b><div class="muted">{html.escape(lead.get('segment',''))}</div></td>
<td>{html.escape(lead.get('contact','') or '—')}<div class="muted">{html.escape(lead.get('email',''))}</div></td>
<td><span class="badge {html.escape(status)}">{html.escape(status)}</span></td>
<td>{html.escape(lead.get('score',''))}</td>
<td>{html.escape(lead.get('next_date','') or '—')}<div class="muted">{html.escape(lead.get('next_action',''))}</div></td>
<td class="notes">{html.escape(lead.get('notes',''))}</td>
</tr>""")
    dashboard = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CRM — Автопарк Контроль</title><style>
:root{{--bg:#f4f5fa;--text:#171a2b;--muted:#667085;--brand:#6d28d9;--line:#e7e9f2}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--text)}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 18px 60px}}h1{{font-size:30px;margin:0 0 4px;letter-spacing:-.7px}}.lead{{color:var(--muted);margin:0 0 22px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}.card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 8px 22px rgba(15,23,42,.05)}}
.card small{{color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.4px}}.card b{{display:block;font-size:28px;margin-top:4px}}
.tools{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}}.btn{{display:inline-flex;padding:10px 14px;border-radius:10px;background:#fff;border:1px solid var(--line);color:var(--text);text-decoration:none;font-weight:700;font-size:13px}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#4f46e5);color:#fff;border:0}}
.table{{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:auto;box-shadow:0 8px 22px rgba(15,23,42,.05)}}table{{width:100%;border-collapse:collapse;font-size:13px;min-width:860px}}th{{text-align:left;font-size:10px;text-transform:uppercase;color:var(--muted);padding:12px;border-bottom:1px solid var(--line)}}td{{padding:12px;border-bottom:1px solid #f1f3f8;vertical-align:top}}tr:last-child td{{border:0}}.muted{{color:var(--muted);font-size:11px;margin-top:2px}}.notes{{max-width:260px;color:var(--muted);font-size:12px}}
.badge{{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:11px;font-weight:800}}.badge.contacted{{background:#fef3c7;color:#92400e}}.badge.new{{background:#dbeafe;color:#1d4ed8}}.badge.replied{{background:#dcfce7;color:#166534}}.badge.won{{background:#bbf7d0;color:#166534}}.badge.lost{{background:#fee2e2;color:#991b1b}}
.note{{margin-top:16px;padding:12px 14px;border-radius:12px;background:#f5f3ff;color:#4c1d95;font-size:13px}}@media(max-width:760px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<h1>CRM — Автопарк Контроль</h1><p class="lead">MVP-воронка: лиды, черновики, follow-up и статусы. Дата: {html.escape(args.today)}</p>
<div class="cards">
<div class="card"><small>Всего лидов</small><b>{total}</b></div>
<div class="card"><small>Написано</small><b>{by_status.get('contacted',0)}</b></div>
<div class="card"><small>Ждут follow-up</small><b>{due}</b></div>
<div class="card"><small>Черновиков</small><b>{draft_count}</b></div>
</div>
<div class="tools"><a class="btn primary" href="../max.html">Презентация</a><a class="btn" href="chat.html">FAQ-бот</a><a class="btn" href="leads.csv">leads.csv</a><a class="btn" href="queue.csv">queue.csv</a></div>
<div class="table"><table><thead><tr><th>Компания</th><th>Контакт</th><th>Статус</th><th>Скор</th><th>Следующий шаг</th><th>Заметки</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">Пока нет лидов</td></tr>'}</tbody></table></div>
<div class="note">Правило MVP: не больше 5 писем в день, только публичные деловые адреса, обязательный opt-out, отправка после <b>approved=yes</b>.</div>
</div></body></html>"""
    DASHBOARD.write_text(dashboard, encoding="utf-8")
    print(f"Готово: {created} черновиков, {total} лидов, {draft_count} в очереди")
    print(f"Дашборд: {DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
