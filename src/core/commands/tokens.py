from __future__ import annotations

from typing import Any

from core.context.compression import estimate_tokens
from core.terminal.cli_output import print_title_and_content

COMMAND = "/tokens"
DESCRIPTION = "查看当前会话token用量"


def handle(history: list[dict[str, Any] | Any] | None, token_threshold: int = 0) -> bool:
    messages = history or []
    used = estimate_tokens(messages)
    if token_threshold > 0:
        remaining = max(0, token_threshold - used)
        percent = min(999.9, (used / token_threshold) * 100)
        print_title_and_content(
            "ai",
            "\n".join(
                [
                    f"当前会话估算用量: {used}",
                    f"距离自动压缩剩余: {remaining}",
                    f"已使用比例: {percent:.1f}%",
                ]
            ),
            title="Session Tokens",
        )
        return False

    print_title_and_content("ai", f"当前会话估算用量: {used}", title="Session Tokens")
    return False
