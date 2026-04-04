from typing import Any

from core.tools.common import safe_path


def run_read_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    limit = arguments.get("limit")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if limit is not None and not isinstance(limit, int):
        raise ValueError("limit 参数必须是整数。")
    if isinstance(limit, int) and limit < 0:
        raise ValueError("limit 参数不能小于 0。")

    try:
        lines = safe_path(path_str).read_text(encoding="utf-8").splitlines()
        if limit is not None and limit < len(lines):
            remaining = len(lines) - limit
            lines = lines[:limit] + [f"... ({remaining} more)"]
        return "\n".join(lines)[:50000]
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "read_file"
TOOL_HANDLER = run_read_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "读取工作区内文件内容，可选返回前若干行。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "工作区内的相对文件路径"},
            "limit": {
                "type": ["integer", "null"],
                "description": "最多返回的行数，可选；null 表示不限制",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}
