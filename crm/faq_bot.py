#!/usr/bin/env python3
"""Small FAQ bot over crm/knowledge.json. Can be used by a future MAX/Telegram adapter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load() -> dict:
    return json.loads((BASE / "knowledge.json").read_text(encoding="utf-8"))


def answer(text: str, data: dict) -> str:
    text = text.lower().replace("ё", "е")
    best = None
    best_score = 0
    for item in data["items"]:
        score = sum(1 for keyword in item["keywords"] if keyword.lower().replace("ё", "е") in text)
        if score > best_score:
            best, best_score = item, score
    return best["answer"] if best else data["fallback"]


def main() -> int:
    parser = argparse.ArgumentParser(description="FAQ bot for Autopark Control")
    parser.add_argument("--question", help="One question and exit")
    args = parser.parse_args()
    data = load()
    if args.question:
        print(answer(args.question, data))
        return 0
    print(f"{data['bot']['name']}\n{data['bot']['disclosure']}\n")
    while True:
        try:
            question = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"выход", "exit", "quit"}:
            break
        print("Бот:", answer(question, data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
