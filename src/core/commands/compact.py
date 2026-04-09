from __future__ import annotations

from typing import Any

from openai import OpenAI

from core.context.compression import compact_history
from core.terminal.cli_output import print_text, Colors

COMMAND = "/compact"
DESCRIPTION = "手动压缩当前会话上下文"


def handle(
    client: OpenAI | None,
    model: str | None,
    history: list[dict[str, Any] | Any] | None,
    keep_recent_messages_count: int = 0,
) -> bool:
    if client is None or not model or history is None:
        return False

    print_text(Colors.reason, "Compacting...\n")
    history[:] = compact_history(
        client=client,
        model=model,
        history=history,
        keep_recent_messages_count=keep_recent_messages_count,
    )
    print_text(Colors.reason, "Compacted\n\n")
    return False
