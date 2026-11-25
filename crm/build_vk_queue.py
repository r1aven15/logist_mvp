#!/usr/bin/env python3
"""Rebuild the VK queue and content plan from crm/max_channel_queue.json."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_QUEUE = BASE / "max_channel_queue.json"
VK_QUEUE = BASE / "vk_channel_queue.json"
CONTENT_PLAN = BASE / "vk_content_plan.md"

MAX_LINK = "https://max.ru/se15129408_bot"
PRESENTATION = "https://r1aven15.github.io/logist_mvp/offer-krsk.html"
DEMO = "https://r1aven15.github.io/logist_mvp/demo-krsk.html"
SITE = "https://r1aven15.github.io/logist_mvp/"


def build(start: date) -> tuple[list[dict], str]:
    posts = json.loads(MAX_QUEUE.read_text(encoding="utf-8"))
    vk_posts = []
    for index, post in enumerate(posts, 1):
        text = post["text"].rstrip()
        footer = ["", "Ссылки:", f"Презентация: {PRESENTATION}", f"Демо: {DEMO}"]
        if MAX_LINK not in text:
            footer.append(f"МАКС: {MAX_LINK}")
        vk_posts.append({
            "id": index,
            "title": post.get("title", f"Пост {index}"),
            "text": text + "\n" + "\n".join(footer),
            "pin": bool(post.get("pin")),
            "source": f"max_channel_queue.json#{index}",
        })

    lines = [
        "# ВКонтакте — контент-план",
        "",
        "Рекомендуемый график: **1 пост в день, 10:00 по Красноярску**.",
        "Так меньше похоже на спам и больше шансов, что знакомые дочитают.",
        "",
        "Ссылки для описания сообщества:",
        f"- Сайт: {SITE}",
        f"- Презентация: {PRESENTATION}",
        f"- Демо: {DEMO}",
        f"- МАКС: {MAX_LINK}",
        "",
        "Если автопостинг через API не разрешат, этот файл можно листать и публиковать вручную.",
        "В VK у записи есть таймер: «Добавить запись» → часы → дата и время.",
        "",
    ]
    for offset, post in enumerate(vk_posts):
        day = start + timedelta(days=offset)
        lines.append(f"## {offset + 1}. {day.strftime('%d.%m.%Y')}, 10:00 — {post['title']}")
        lines.append("")
        lines.append(post["text"])
        lines.append("")
    return vk_posts, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD; default is tomorrow")
    args = parser.parse_args()
    start = date.fromisoformat(args.start) if args.start else date.today() + timedelta(days=1)
    vk_posts, plan = build(start)
    VK_QUEUE.write_text(json.dumps(vk_posts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONTENT_PLAN.write_text(plan, encoding="utf-8")
    print(f"VK queue: {len(vk_posts)} posts")
    print(f"Content plan: {CONTENT_PLAN} ({CONTENT_PLAN.stat().st_size} bytes)")
    print(f"Start: {start.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
