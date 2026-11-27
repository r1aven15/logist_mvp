#!/usr/bin/env python3
"""Publish VK community posts from crm/vk_channel_queue.json.

VK restricts wall.post for new apps. If the API returns an access error,
use crm/vk_content_plan.md and schedule posts manually in VK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
QUEUE_FILE = BASE / "vk_channel_queue.json"
STATE_FILE = BASE / ".vk_channel_state.json"
LOG_FILE = BASE / "vk_channel.log"
API = "https://api.vk.com/method/wall.post"
DEFAULT_ATTACHMENT = "https://r1aven15.github.io/logist_mvp/offer-krsk.html"
VK_VERSION = "5.199"


class VkError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"VK error {code}: {message}")
        self.code = code
        self.message = message


def log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        raise SystemExit(f"Нет файла {QUEUE_FILE}. Сначала собери очередь.")
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"posted": [], "last_post_id": None}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"posted": [], "last_post_id": None}
    state.setdefault("posted", [])
    state.setdefault("last_post_id", None)
    return state


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def next_post(queue: list[dict], state: dict) -> dict | None:
    posted = set(state.get("posted", [])) | set(state.get("scheduled", []))
    for post in queue:
        if post["id"] not in posted:
            return post
    return None


def call_vk(token: str, group_id: str, message: str, attachment: str | None) -> int:
    params = {
        "owner_id": f"-{group_id.lstrip('-')}",
        "from_group": "1",
        "message": message,
        "guid": hashlib.sha1(f"{group_id}:{message[:200]}".encode("utf-8")).hexdigest(),
        "access_token": token,
        "v": VK_VERSION,
    }
    if attachment:
        params["attachments"] = attachment
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(API, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise VkError(exc.code, exc.reason) from exc
    if "error" in payload:
        error = payload["error"]
        raise VkError(int(error.get("error_code", 0)), str(error.get("error_msg", "unknown")))
    return int(payload["response"]["post_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a VK community post")
    parser.add_argument("--index", type=int, help="Post number from the queue (1-based)")
    parser.add_argument("--list", action="store_true", help="Show queue and posted state")
    parser.add_argument("--dry-run", action="store_true", help="Print the post without sending")
    parser.add_argument("--send", action="store_true", help="Actually call VK API")
    parser.add_argument("--force", action="store_true", help="Allow re-posting an already posted item")
    parser.add_argument("--reset-state", action="store_true", help="Forget posted state")
    parser.add_argument("--attachment", default=os.getenv("VK_ATTACHMENT_URL", DEFAULT_ATTACHMENT))
    args = parser.parse_args()

    queue = load_queue()
    state = load_state()

    if args.reset_state:
        state = {"posted": [], "last_post_id": None}
        save_state(state)
        log("Состояние VK сброшено.")
        return 0

    if args.list:
        posted = set(state.get("posted", []))
        scheduled = set(state.get("scheduled", []))
        for post in queue:
            mark = "✓" if post["id"] in posted else "◷" if post["id"] in scheduled else " "
            print(f"[{mark}] {post['id']:>2}. {post['title']}")
        return 0

    if args.index:
        if args.index < 1 or args.index > len(queue):
            raise SystemExit(f"Индекс вне диапазона: 1..{len(queue)}")
        post = queue[args.index - 1]
    else:
        post = next_post(queue, state)
        if not post:
            log("Все посты уже опубликованы. Сбрось состояние: --reset-state")
            return 0

    if (post["id"] in state.get("posted", []) or post["id"] in state.get("scheduled", [])) and not args.force:
        log(f"Пост {post['id']} уже опубликован или запланирован. Для повтора добавь --force.")
        return 0

    print(f"Пост {post['id']}/{len(queue)}: {post['title']}")
    print("-" * 60)
    print(post["text"])
    print("-" * 60)

    if not args.send:
        log("Dry run: в VK ничего не отправлено. Добавь --send.")
        return 0

    token = os.getenv("VK_ACCESS_TOKEN", "").strip()
    group_id = os.getenv("VK_GROUP_ID", "").strip()
    if not token or not group_id:
        log("VK_ACCESS_TOKEN или VK_GROUP_ID не заданы. Смотри crm/VK_CHANNEL.md.")
        return 0

    try:
        post_id = call_vk(token, group_id, post["text"], args.attachment or None)
    except VkError as exc:
        log(str(exc))
        if exc.code in (15, 214, 222):
            log("VK ограничил автопостинг. Открой crm/vk_content_plan.md и опубликуй вручную.")
        return 1

    state["posted"].append(post["id"])
    state["last_post_id"] = post_id
    save_state(state)
    log(f"Опубликовано: https://vk.com/wall-{group_id.lstrip('-')}_{post_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
