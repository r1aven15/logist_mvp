#!/usr/bin/env python3
"""MAX bot adapter for Business Assistant.

Inbound only: the bot answers people who start it or write to it.
Token is read from .secrets/max-bot-token or MAX_BOT_TOKEN.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from faq_bot import answer, load

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOKEN_FILE = ROOT / ".secrets" / "max-bot-token"
MARKER_FILE = BASE / ".max_marker"
API = "https://platform-api.max.ru"

DEMO = "https://r1aven15.github.io/logist_mvp/demo-krsk.html"
PRESENTATION = "https://r1aven15.github.io/logist_mvp/offer-krsk.html"
PDF = "https://r1aven15.github.io/logist_mvp/offer-krsk.pdf"
PHONE = "+7 983 502-45-66"
EMAIL = "vsend15@mail.ru"
WHATSAPP = "https://wa.me/79835024566"

WELCOME = (
    "Здравствуйте! Я Бизнес-Помощник — автоматический помощник.\n\n"
    "Помогаю навести порядок в бизнесе: автопарк, финансы, налоги, "
    "отчёты и автоматизация. На сложные вопросы отвечает Владимир.\n\n"
    "С чего начнём?"
)

PRICES = (
    "Тарифы «Автопарк Контроль»:\n"
    "• Старт — 2 490 ₽/мес, до 5 машин\n"
    "• Парк — 4 990 ₽/мес, до 15 машин\n"
    "• Бизнес — 8 990 ₽/мес, до 30 машин\n\n"
    "В облаке хостинг, обновления и резервные копии включены. "
    "Внедрение и перенос данных — 9 900 ₽ разово.\n\n"
    "Для первых 10 компаний — бесплатный пилот. Точную стоимость "
    "фиксируем после демо."
)

CONTACT = (
    "Владимир Анисимов\n"
    f"Телефон: {PHONE}\n"
    f"Почта: {EMAIL}\n"
    f"WhatsApp: {WHATSAPP}\n\n"
    "Напишите, сколько у вас машин и какой тип перевозок — "
    "подготовлю демо на вашем примере."
)

MENU = {
    "buttons": [
        [{"type": "callback", "text": "Демо автопарка", "payload": "demo"}],
        [
            {"type": "callback", "text": "Презентация", "payload": "presentation"},
            {"type": "callback", "text": "Цены", "payload": "price"},
        ],
        [
            {"type": "callback", "text": "Пилот", "payload": "pilot"},
            {"type": "callback", "text": "Связаться", "payload": "contact"},
        ],
    ]
}


def load_token() -> str:
    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("MAX_BOT_TOKEN не задан")
    return token


TOKEN = load_token()


def api(method: str, path: str, payload: dict | None = None, timeout: int = 45) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": TOKEN,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def send(chat_id: int | str | None = None, user_id: int | str | None = None,
         text: str = "", keyboard: dict | None = None) -> None:
    params = []
    if chat_id is not None:
        params.append(f"chat_id={chat_id}")
    elif user_id is not None:
        params.append(f"user_id={user_id}")
    else:
        return
    query = "&".join(params)
    body: dict = {"text": text, "notify": True}
    if keyboard:
        body["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
    try:
        api("POST", f"/messages?{query}", body)
    except urllib.error.HTTPError as exc:
        print(f"send HTTP {exc.code}: {exc.read(500).decode('utf-8', 'replace')}")
    except Exception as exc:
        print(f"send error: {type(exc).__name__}: {exc}")


def answer_callback(callback_id: str, notification: str | None = None) -> None:
    if not callback_id:
        return
    payload = {}
    if notification:
        payload["notification"] = notification
    try:
        api("POST", f"/answers?callback_id={callback_id}", payload)
    except Exception as exc:
        print(f"callback answer error: {type(exc).__name__}")


def handle_callback(update: dict) -> None:
    callback = update.get("callback") or {}
    callback_id = callback.get("callback_id", "")
    payload = callback.get("payload", "")
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    user_id = (callback.get("user") or {}).get("user_id")

    if payload == "demo":
        text = (
            "Демо «Автопарк Контроль» открывается без установки:\n"
            f"{DEMO}\n\n"
            "Там смешанный парк, рейсы, ГСМ, отчёты и выгрузка в 1С/Excel."
        )
        answer_callback(callback_id, "Открываю демо")
        send(chat_id=chat_id, user_id=user_id, text=text, keyboard=MENU)
    elif payload == "presentation":
        text = (
            "Презентация и PDF:\n"
            f"{PRESENTATION}\n{PDF}\n\n"
            "Можно открыть с телефона и отправить бухгалтеру."
        )
        answer_callback(callback_id, "Отправляю ссылки")
        send(chat_id=chat_id, user_id=user_id, text=text, keyboard=MENU)
    elif payload == "price":
        answer_callback(callback_id, "Тарифы")
        send(chat_id=chat_id, user_id=user_id, text=PRICES, keyboard=MENU)
    elif payload == "pilot":
        text = (
            "Пилот для первых 10 компаний:\n"
            "• бесплатное демо;\n"
            "• перенос данных;\n"
            "• настройка под ваш парк;\n"
            "• помощь с отчётами для бухгалтера.\n\n"
            "Напишите, сколько машин и какой тип перевозок."
        )
        answer_callback(callback_id, "Пилот")
        send(chat_id=chat_id, user_id=user_id, text=text, keyboard=MENU)
    elif payload == "contact":
        answer_callback(callback_id, "Контакты")
        send(chat_id=chat_id, user_id=user_id, text=CONTACT, keyboard=MENU)
    else:
        answer_callback(callback_id, "Главное меню")
        send(chat_id=chat_id, user_id=user_id, text=WELCOME, keyboard=MENU)


def handle_text(update: dict) -> None:
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("is_bot"):
        return
    recipient = message.get("recipient") or {}
    if recipient.get("chat_type") != "dialog":
        return
    chat_id = recipient.get("chat_id")
    user_id = sender.get("user_id")
    body = message.get("body") or {}
    text = (body.get("text") or "").strip()
    if not text:
        return

    command = text.split()[0].lower().lstrip("/")
    if command in {"start", "menu", "help", "начать"}:
        send(chat_id=chat_id, user_id=user_id, text=WELCOME, keyboard=MENU)
    elif command in {"demo", "демо"}:
        send(
            chat_id=chat_id,
            user_id=user_id,
            text=f"Демо открывается без установки:\n{DEMO}\n\nПокажу на вашем примере за 10 минут.",
            keyboard=MENU,
        )
    elif command in {"presentation", "презентация", "pdf"}:
        send(
            chat_id=chat_id,
            user_id=user_id,
            text=f"Презентация:\n{PRESENTATION}\n\nPDF:\n{PDF}",
            keyboard=MENU,
        )
    elif command in {"price", "цены", "тарифы"}:
        send(chat_id=chat_id, user_id=user_id, text=PRICES, keyboard=MENU)
    elif command in {"contact", "связаться", "контакты"}:
        send(chat_id=chat_id, user_id=user_id, text=CONTACT, keyboard=MENU)
    elif command in {"pilot", "пилот"}:
        send(
            chat_id=chat_id,
            user_id=user_id,
            text=(
                "Пилот для первых 10 компаний: бесплатное демо, перенос данных "
                "и настройка под ваш парк. Напишите, сколько машин и какой тип перевозок."
            ),
            keyboard=MENU,
        )
    else:
        data = load()
        reply = answer(text, data)
        send(chat_id=chat_id, user_id=user_id, text=reply, keyboard=MENU)


def process(update: dict) -> None:
    kind = update.get("update_type")
    if kind == "bot_started":
        send(chat_id=update.get("chat_id"), text=WELCOME, keyboard=MENU)
    elif kind == "message_created":
        handle_text(update)
    elif kind == "message_callback":
        handle_callback(update)


def main() -> int:
    marker = MARKER_FILE.read_text(encoding="utf-8").strip() if MARKER_FILE.exists() else ""
    print("MAX bot started")
    while True:
        query = "/updates?timeout=30&limit=100"
        if marker:
            query += f"&marker={marker}"
        try:
            data = api("GET", query, timeout=45)
            for update in data.get("updates", []):
                try:
                    process(update)
                except Exception as exc:
                    print(f"process error: {type(exc).__name__}: {exc}")
            new_marker = data.get("marker")
            if new_marker:
                marker = str(new_marker)
                MARKER_FILE.write_text(marker, encoding="utf-8")
        except urllib.error.HTTPError as exc:
            print(f"updates HTTP {exc.code}: {exc.read(300).decode('utf-8', 'replace')}")
            time.sleep(3)
        except Exception as exc:
            print(f"updates error: {type(exc).__name__}: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
