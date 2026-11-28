#!/usr/bin/env python3
"""CargoHunt Telegram bot: FAQ, lead qualification and CRM capture.

Inbound only. The bot never messages people who did not start it.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from faq_bot import answer, load
from send_queue import load_env as load_smtp_env, smtp_send

BASE = Path(__file__).resolve().parent
LEADS = BASE / "leads.csv"
TG_LEADS = BASE / "telegram_leads.csv"
OFFSET = BASE / ".telegram_offset"
SESSIONS: dict[int, dict] = {}
LEAD_FIELDS = ["created_at", "chat_id", "username", "name", "company", "fleet", "phone", "status"]
LEAD_FIELDS_LEADS = ["id", "company", "segment", "city", "website", "email", "phone", "contact", "role", "source", "basis", "status", "score", "last_contact", "next_action", "next_date", "notes", "source_id"]

WELCOME = (
    "Здравствуйте! Я CargoHunt — помощник по учёту автопарка.\n\n"
    "Расскажу про программу, цены, 1С/Excel, сервер и налоги. "
    "Могу передать заявку Владимиру на демо."
)
KEYBOARD = {
    "inline_keyboard": [
        [{"text": "💰 Цены", "callback_data": "price"}, {"text": "🧮 Налоги", "callback_data": "tax"}],
        [{"text": "🖥 1С/Excel", "callback_data": "1c"}, {"text": "☁️ Сервер", "callback_data": "server"}],
        [{"text": "🎯 Хочу демо", "callback_data": "demo"}],
    ]
}
CALLBACK_QUESTIONS = {
    "price": "Сколько стоит?",
    "tax": "Какие налоги?",
    "1c": "Есть ли выгрузка в 1С?",
    "server": "Где хранятся данные?",
}


def load_env() -> None:
    env = BASE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()


load_env()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "").strip()
CRM_URL = os.getenv("CRM_URL", "").strip()
if not TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN не задан в crm/.env")


def api(method: str, payload: dict | None = None, timeout: int = 35) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def send(chat_id: int | str, text: str, keyboard: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        api("sendMessage", payload)
    except Exception as exc:
        print(f"send error: {type(exc).__name__}")


def suggested_reply(data: dict) -> str:
    name = data.get("name") or "коллеги"
    return (
        f"Здравствуйте, {name}! Спасибо за заявку по учёту автопарка. "
        "Уточните, пожалуйста, сколько у вас машин и какой тип перевозок — "
        "покажу демо на вашем примере. Владимир, +7 983 502-45-66."
    )


def all_leads() -> list[dict]:
    if not LEADS.exists():
        return []
    with LEADS.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def send_email_notification(chat_id: int, username: str, data: dict) -> None:
    env = load_smtp_env()
    to = NOTIFY_EMAIL or env.get("SMTP_USER", "")
    if not to:
        print("email notification skipped: NOTIFY_EMAIL/SMTP_USER is empty")
        return
    msg = EmailMessage()
    msg["Subject"] = f"CargoHunt: новая заявка — {data.get('company', 'без компании')}"
    msg["From"] = env.get("SMTP_FROM") or env.get("SMTP_USER", "")
    msg["To"] = to
    msg.set_content(
        "Сообщение от AI-агента OpenHands по поручению Владимира Анисимова.\n\n"
        "Новая заявка из Telegram-бота @CargoHuntbot.\n\n"
        f"Имя: {data.get('name', '')}\n"
        f"Компания: {data.get('company', '')}\n"
        f"Парк: {data.get('fleet', '')}\n"
        f"Телефон: {data.get('phone', '')}\n"
        f"Telegram: @{username or chat_id}\n"
        f"chat_id: {chat_id}\n"
        f"Дата: {datetime.now().isoformat(timespec='seconds')}\n\n"
        "Заявка уже сохранена в CRM: crm/leads.csv.\n\n"
        f"Что написать:\n{suggested_reply(data)}\n"
    )
    try:
        smtp_send(msg, env)
        print("email notification sent")
    except Exception as exc:
        print(f"email notification error: {type(exc).__name__}")


def save_lead(chat_id: int, username: str, data: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    row = {"created_at": now, "chat_id": chat_id, "username": username, **data, "status": "new"}
    new_file = not TG_LEADS.exists()
    with TG_LEADS.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEAD_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)

    lead = {
        "id": f"tg-{chat_id}-{int(time.time())}",
        "company": data.get("company", ""),
        "segment": "Telegram-заявка",
        "city": "Красноярск",
        "website": "",
        "email": "",
        "phone": data.get("phone", ""),
        "contact": data.get("name", ""),
        "role": "",
        "source": "Telegram",
        "basis": "inbound_request",
        "status": "new",
        "score": "",
        "last_contact": now[:10],
        "next_action": "call",
        "next_date": now[:10],
        "notes": f"Telegram @{username or chat_id}; парк: {data.get('fleet', '')}",
        "source_id": f"tg:{chat_id}:{int(time.time())}",
    }
    new_leads = not LEADS.exists()
    with LEADS.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEAD_FIELDS_LEADS, extrasaction="ignore")
        if new_leads:
            writer.writeheader()
        writer.writerow(lead)

    send_email_notification(chat_id, username, data)

    if ADMIN_ID:
        send(
            ADMIN_ID,
            "Новая заявка из Telegram\n"
            f"Имя: {data.get('name', '')}\n"
            f"Компания: {data.get('company', '')}\n"
            f"Парк: {data.get('fleet', '')}\n"
            f"Телефон: {data.get('phone', '')}\n"
            f"Контакт: @{username or chat_id}\n\n"
            f"Что написать:\n{suggested_reply(data)}"
            + (f"\n\nCRM: {CRM_URL}" if CRM_URL else ""),
        )


def start_demo(chat_id: int, username: str) -> None:
    SESSIONS[chat_id] = {"step": "name", "data": {}, "username": username}
    send(chat_id, "Отлично. Как вас зовут?")


def handle_lead_step(chat_id: int, username: str, text: str) -> bool:
    session = SESSIONS.get(chat_id)
    if not session:
        return False
    step = session["step"]
    data = session["data"]
    if step == "name":
        data["name"] = text.strip()[:120]
        session["step"] = "company"
        send(chat_id, "Компания и город? Например: ООО Ромашка, Красноярск")
    elif step == "company":
        data["company"] = text.strip()[:180]
        session["step"] = "fleet"
        send(chat_id, "Сколько машин в парке?")
    elif step == "fleet":
        data["fleet"] = text.strip()[:80]
        session["step"] = "phone"
        send(chat_id, "Телефон для связи?")
    elif step == "phone":
        digits = re.sub(r"\D", "", text)
        if len(digits) < 10:
            send(chat_id, "Проверьте номер: нужно не меньше 10 цифр.")
            return True
        data["phone"] = text.strip()[:40]
        save_lead(chat_id, username, data)
        SESSIONS.pop(chat_id, None)
        send(chat_id, "Спасибо! Передал Владимиру. Он свяжется и покажет демо на вашем примере.")
    return True


def handle_message(message: dict) -> None:
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return
    text = (message.get("text") or "").strip()
    username = chat.get("username") or chat.get("first_name") or ""
    if not text:
        return
    lower = text.lower()

    if lower.startswith("/start"):
        SESSIONS.pop(chat_id, None)
        send(chat_id, WELCOME, KEYBOARD)
        return
    if lower == "/id":
        send(chat_id, f"Ваш chat_id: {chat_id}\nUsername: @{username or 'нет'}")
        return
    if lower in {"/cancel", "отмена"}:
        SESSIONS.pop(chat_id, None)
        send(chat_id, "Отменил. Можете задать вопрос или нажать «Хочу демо».")
        return
    if lower == "/help":
        send(chat_id, "Команды: /start, /id, /cancel, /help, /leads, /new, /crm.\nИли просто напишите вопрос.")
        return
    if lower == "/crm" and ADMIN_ID and str(chat_id) == ADMIN_ID:
        send(chat_id, f"CRM: {CRM_URL}" if CRM_URL else "CRM_URL не задан")
        return
    if lower in {"/leads", "/new"} and ADMIN_ID and str(chat_id) == ADMIN_ID:
        rows = all_leads()
        if lower == "/new":
            rows = [r for r in rows if r.get("status") == "new"]
        rows = rows[-10:]
        if not rows:
            send(chat_id, "Лидов нет.")
            return
        lines = ["Последние заявки:" if lower == "/leads" else "Новые заявки:"]
        for row in reversed(rows):
            lines.append(
                f"• {row.get('company') or 'Без компании'} — {row.get('contact') or '—'}, "
                f"{row.get('phone') or '—'} [{row.get('status') or 'new'}]"
            )
        if CRM_URL:
            lines.append(f"\nCRM: {CRM_URL}")
        send(chat_id, "\n".join(lines))
        return
    if lower == "/stats" and ADMIN_ID and str(chat_id) == ADMIN_ID:
        rows = list(csv.DictReader(LEADS.open(encoding="utf-8"))) if LEADS.exists() else []
        send(chat_id, f"Лидов: {len(rows)}\nНовых: {sum(1 for r in rows if r.get('status') == 'new')}")
        return
    if any(word in lower for word in ("демо", "связаться", "позвоните", "оставить заявку")):
        start_demo(chat_id, username)
        return
    if handle_lead_step(chat_id, username, text):
        return
    send(chat_id, answer(text, load()), KEYBOARD)


def handle_callback(callback: dict) -> None:
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    data = callback.get("data", "")
    if not chat_id:
        return
    try:
        api("answerCallbackQuery", {"callback_query_id": callback.get("id")})
    except Exception:
        pass
    if data == "demo":
        start_demo(chat_id, callback.get("from", {}).get("username", ""))
        return
    question = CALLBACK_QUESTIONS.get(data)
    if question:
        send(chat_id, answer(question, load()), KEYBOARD)


def load_offset() -> int:
    try:
        return int(OFFSET.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def save_offset(value: int) -> None:
    OFFSET.write_text(str(value), encoding="utf-8")


def main() -> int:
    me = api("getMe").get("result", {})
    print(f"Bot @{me.get('username')} started; admin={'set' if ADMIN_ID else 'not set'}")
    offset = load_offset()
    while True:
        try:
            updates = api("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]}, timeout=35).get("result", [])
        except urllib.error.HTTPError as exc:
            print(f"poll HTTP error: {exc.code}")
            time.sleep(3)
            continue
        except Exception as exc:
            print(f"poll error: {type(exc).__name__}")
            time.sleep(3)
            continue
        for update in updates:
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            save_offset(offset)
            if "message" in update:
                handle_message(update["message"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
