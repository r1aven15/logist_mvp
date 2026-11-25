#!/usr/bin/env python3
"""Show how full the current OpenHands context is."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONVERSATIONS = Path("/var/openhands/conversations")


def latest_conversation() -> Path | None:
    if not CONVERSATIONS.exists():
        return None
    candidates = [
        path for path in CONVERSATIONS.iterdir()
        if path.is_dir() and (path / "base_state.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path / "base_state.json").stat().st_mtime)


def usage(conversation: Path) -> dict:
    state = json.loads((conversation / "base_state.json").read_text(encoding="utf-8"))
    agent = state.get("stats", {}).get("usage_to_metrics", {}).get("agent", {})
    tokens = agent.get("accumulated_token_usage", {})
    used = int(tokens.get("per_turn_token") or 0)
    window = int(tokens.get("context_window") or 0)
    percent = (used / window * 100) if window else 0.0
    return {
        "conversation": conversation.name,
        "model": agent.get("model_name", "unknown"),
        "used_tokens": used,
        "context_window": window,
        "percent": round(percent, 1),
        "accumulated_cost": agent.get("accumulated_cost", 0),
        "prompt_tokens": tokens.get("prompt_tokens", 0),
        "completion_tokens": tokens.get("completion_tokens", 0),
    }


def main() -> int:
    conversation = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_conversation()
    if not conversation:
        print("Не нашёл историю чата. Укажи путь к папке conversation.")
        return 1
    data = usage(conversation)
    print(f"Модель: {data['model']}")
    print(
        f"Контекст: {data['used_tokens']:,} / {data['context_window']:,} токенов "
        f"= {data['percent']}%"
    )
    if data["percent"] >= 95:
        print("🔴 95%+ — сохрани контекст и начни новый чат.")
    elif data["percent"] >= 85:
        print("🟠 85%+ — скоро предел; сохрани контекст.")
    elif data["percent"] >= 70:
        print("🟡 70%+ — пора сохранить контекст и, возможно, начать новый чат.")
    else:
        print("🟢 Запас есть.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
