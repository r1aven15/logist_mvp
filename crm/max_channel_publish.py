#!/usr/bin/env python3
"""Publish queued MAX channel posts with idempotent catch-up.

Slots are 10:00, 15:00 and 20:00 Krasnoyarsk (UTC+7). The workflow can run
more often than the slots: before sending, the script checks recent channel
messages and skips a post that is already there. That makes a delayed or
missed GitHub Actions run safe and lets the next run catch up.
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
SLOT_TIMES = {"morning": (10, 0), "day": (15, 0), "evening": (20, 0)}


def load_token() -> str:
    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("MAX_BOT_TOKEN не задан")
    return token


def api(method: str, path: str, payload: dict | None = None, timeout: int = 45) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": load_token(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def recent_texts() -> list[str] | None:
    """Return recent channel texts, or None when history cannot be read."""
    try:
        data = api("GET", f"/messages?chat_id={CHANNEL_ID}&count=50")
    except Exception as exc:
        print(f"history read error: {type(exc).__name__}: {exc}")
        return None
    texts = []
    for message in data.get("messages", []):
        text = (message.get("body") or {}).get("text") or ""
        if text:
            texts.append(text)
    return texts


def normalize(text: str) -> str:
    return " ".join(str(text).split())


def already_sent(text: str, recent: list[str]) -> bool:
    needle = normalize(text)[:120]
    return any(needle in normalize(item) for item in recent)


def due_slots(now: datetime) -> list[str]:
    minutes = now.hour * 60 + now.minute
    return [
        slot for slot in ("morning", "day", "evening")
        if minutes >= SLOT_TIMES[slot][0] * 60 + SLOT_TIMES[slot][1]
    ]


def queue_post(posts: list[dict], slot: str, now: datetime) -> tuple[int, dict]:
    index = (now.date().toordinal() * 3 + SLOT_INDEX[slot]) % len(posts)
    return index, posts[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="auto", choices=["auto", *SLOT_INDEX])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_date = os.getenv("START_DATE", "").strip()
    now = datetime.now(LOCAL_TZ)
    if start_date and now.date().isoformat() < start_date:
        print(f"workflow starts on {start_date}")
        return 0

    candidates = [args.slot] if args.slot != "auto" else due_slots(now)
    if not candidates:
        print("no slot due yet")
        return 0

    posts = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    recent = recent_texts()
    if recent is None:
        print("channel history unavailable; refusing to post to avoid duplicates")
        return 1

    for slot in candidates:
        index, post = queue_post(posts, slot, now)
        title = post.get("title", "")
        if already_sent(post["text"], recent):
            print(f"skip {slot}: {index + 1}/{len(posts)} {title} already published")
            continue
        if args.dry_run:
            print(f"would publish {slot}: {index + 1}/{len(posts)} {title}")
            return 0
        result = api("POST", f"/messages?chat_id={CHANNEL_ID}", {"text": post["text"], "notify": True})
        message = result.get("message") or {}
        mid = (message.get("body") or {}).get("mid", "")
        if post.get("pin") and mid:
            try:
                api("PUT", f"/chats/{CHANNEL_ID}/pin", {"message_id": mid, "notify": False})
            except urllib.error.HTTPError as exc:
                print(f"pin HTTP {exc.code}")
        print(f"published {slot}: {index + 1}/{len(posts)} {title} {mid}")
        return 0

    print("all due posts already published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
