from __future__ import annotations

from typing import Any

from core.terminal.cli_output import Colors, print_text

COMMAND = "/clear"
DESCRIPTION = "清空当前会话历史"


def handle(history: list[dict[str, Any] | Any] | None) -> bool:
    if history is None:
        return False

    developer_messages = [
        item
        for item in history
        if isinstance(item, dict) and item.get("role") == "developer"
    ]
    cleared_count = max(0, len(history) - len(developer_messages))
    history[:] = developer_messages
    print_text(Colors.green, f"已清空当前会话历史，移除了 {cleared_count} 条消息。\n\n")
    return False
