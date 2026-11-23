#!/usr/bin/env python3
"""Publish three queued posts per day to the MAX channel.

Slots are 10:00, 15:00 and 20:00 Krasnoyarsk (UTC+7).
The next slot is stored on disk, so a restart does not duplicate a post.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOKEN_FILE = ROOT / ".secrets" / "max-bot-token"
QUEUE_FILE = BASE / "max_channel_queue.json"
STATE_FILE = BASE / ".max_channel_state.json"
API = "https://platform-api.max.ru"
CHANNEL_ID = -81571822668314
LOCAL_TZ = timezone(timedelta(hours=7))
SLOTS = [(10, 0), (15, 0), (20, 0)]
STOP_AFTER = os.getenv("MAX_CHANNEL_STOP_AFTER", "2026-11-23")


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
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def next_slot(after: datetime) -> datetime:
    for day_offset in range(0, 8):
        day = after.date() + timedelta(days=day_offset)
        for hour, minute in SLOTS:
            candidate = datetime.combine(day, dt_time(hour, minute), LOCAL_TZ)
            if candidate > after:
                return candidate
    return after + timedelta(days=1)


def read_state() -> dict:
    if not STATE_FILE.exists():
        state = {"next": 0, "next_at": next_slot(datetime.now(LOCAL_TZ)).isoformat()}
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return state
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def write_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def send(text: str) -> dict:
    return api("POST", f"/messages?chat_id={CHANNEL_ID}", {"text": text, "notify": True})


def pin(message_id: str) -> None:
    if not message_id:
        return
    try:
        api("PUT", f"/chats/{CHANNEL_ID}/pin", {"message_id": message_id, "notify": False})
    except Exception as exc:
        print(f"pin error: {type(exc).__name__}: {exc}")


def publish_next() -> bool:
    posts = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    state = read_state()
    index = int(state.get("next", 0))
    if index >= len(posts):
        print("queue finished")
        return False
    post = posts[index]
    try:
        result = send(post["text"])
    except urllib.error.HTTPError as exc:
        print(f"publish HTTP {exc.code}: {exc.read(300).decode('utf-8', 'replace')}")
        return False
    except Exception as exc:
        print(f"publish error: {type(exc).__name__}: {exc}")
        return False

    message = result.get("message") or {}
    mid = (message.get("body") or {}).get("mid", "")
    if post.get("pin") and mid:
        pin(mid)

    state["next"] = index + 1
    state["next_at"] = next_slot(datetime.now(LOCAL_TZ)).isoformat()
    write_state(state)
    print(f"published {index + 1}/{len(posts)}: {post.get('title', '')} {mid}")
    return True


def main() -> int:
    print("channel scheduler started (3 posts/day: 10:00, 15:00, 20:00)")
    while True:
        now = datetime.now(LOCAL_TZ)
        state = read_state()
        next_at = datetime.fromisoformat(state["next_at"])
        if now >= next_at:
            published = publish_next()
            if published and now.date().isoformat() >= STOP_AFTER:
                print("local scheduler stopped; GitHub Actions takes over")
                return 0
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
