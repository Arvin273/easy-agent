from __future__ import annotations

from typing import Any

TOOL_NAME = "compact"


def run_compact(_: dict[str, Any]) -> str:
    return "Manual compression requested."


TOOL_HANDLER = run_compact
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "手动触发会话压缩，总结上下文后继续。",
    "parameters": {
        "type": "object",
        "properties": {
            "focus": {
                "type": ["string", "null"],
                "description": "可选：压缩时优先保留的关注点",
            }
        },
        "required": [],
        "additionalProperties": False,
    },
}

