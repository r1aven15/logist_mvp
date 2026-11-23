#!/usr/bin/env python3
"""Publish one queued post for a specific daily slot.

Designed for GitHub Actions: no local state, the post is selected from the
date and slot. Slots: morning 10:00, day 15:00, evening 20:00 (UTC+7).
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOKEN_FILE = ROOT / ".secrets" / "max-bot-token"
QUEUE_FILE = BASE / "max_channel_queue.json"
API = "https://platform-api.max.ru"
CHANNEL_ID = -81571822668314
LOCAL_TZ = timezone(timedelta(hours=7))
SLOT_INDEX = {"morning": 0, "day": 1, "evening": 2}


def load_token() -> str:
    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("MAX_BOT_TOKEN не задан")
    return token


def api(method: str, path: str, payload: dict, timeout: int = 45) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method=method,
        headers={
            "Authorization": load_token(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def resolve_slot(value: str) -> str:
    if value in SLOT_INDEX:
        return value
    hour = datetime.now(LOCAL_TZ).hour
    if hour < 13:
        return "morning"
    if hour < 18:
        return "day"
    return "evening"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="auto", choices=["auto", *SLOT_INDEX])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    slot = resolve_slot(args.slot)
    posts = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    index = (datetime.now(LOCAL_TZ).date().toordinal() * 3 + SLOT_INDEX[slot]) % len(posts)
    post = posts[index]
    if args.dry_run:
        print(f"{slot}: {index + 1}/{len(posts)} {post['title']}")
        return 0

    result = api("POST", f"/messages?chat_id={CHANNEL_ID}", {"text": post["text"], "notify": True})
    message = result.get("message") or {}
    mid = (message.get("body") or {}).get("mid", "")
    if post.get("pin") and mid:
        try:
            api("PUT", f"/chats/{CHANNEL_ID}/pin", {"message_id": mid, "notify": False})
        except urllib.error.HTTPError as exc:
            print(f"pin HTTP {exc.code}")
    print(f"published {slot}: {index + 1}/{len(posts)} {post.get('title', '')} {mid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
