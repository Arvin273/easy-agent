import json
import shutil
from typing import Any


RESET = "\033[0m"
COLORS = {
    "ai": "\033[32m",
    "tool": "\033[34m",
    "tool_calling": "\033[33m",
    "error": "\033[31m",
    "user": "\033[36m",
    "reason": "\033[90m",
}


def format_tool_call(tool_call: dict[str, Any]) -> str:
    name = str(tool_call.get("name", "unknown"))
    args = tool_call.get("args", {})
    if not args:
        return f"调用工具: {name}"

    try:
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
    except TypeError:
        args_text = str(args)

    return f"调用工具: {name}\n参数:\n{args_text}"


def print_box(role: str, content: str, title: str | None = None) -> None:
    text = str(content or "").strip()
    if not text:
        return

    color = COLORS.get(role, "")
    header = title or role.upper()
    columns = shutil.get_terminal_size(fallback=(100, 20)).columns
    safe_columns = max(10, columns - 2)
    line_width = max(20, min(60, safe_columns))
    label = f" {header} "
    if len(label) >= line_width:
        label = f" {header[: max(1, line_width - 4)]} "
    top = label.center(line_width, "─")

    print(f"{color}{top}{RESET}")
    print(text)
    print()
