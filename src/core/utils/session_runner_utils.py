from __future__ import annotations

import json
import sys
from typing import Any

from core.tools.bash import TOOL_NAME as BASH_TOOL_NAME
from core.utils.history_items import build_function_call_output_item


def normalize_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        output = result.get("output", "")
        return str(output)
    return str(result)


def _truncate_preview_line(line: str, max_width: int = 160) -> str:
    if len(line) <= max_width:
        return line
    hidden = len(line) - max_width
    return f"{line[:max_width]}... ({hidden} more chars)"


def format_tool_output_preview(output: str, edge_lines: int = 4) -> str:
    lines = output.splitlines()
    if len(lines) <= 1:
        try:
            parsed = json.loads(output)
        except Exception:
            parsed = None
        if parsed is not None:
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            lines = pretty.splitlines()
    lines = [_truncate_preview_line(line) for line in lines]
    max_lines = edge_lines * 2
    if len(lines) <= max_lines:
        return "\n".join(lines)
    hidden = len(lines) - max_lines
    preview_lines = lines[:edge_lines] + [f"... ({hidden} more lines)"] + lines[-edge_lines:]
    return "\n".join(preview_lines)


def should_print_tool_output_preview(tool_name: str, output: str) -> bool:
    # Bash 只在错误、无输出或转后台时打印摘要，避免正常命令刷屏。
    stripped = str(output).strip()
    if not stripped:
        return False
    if tool_name != BASH_TOOL_NAME:
        return True
    return (
            stripped.startswith("Error:")
            or stripped == "(no output)"
            or stripped.startswith("Started background bash task ")
    )


def read_cancel_key_nonblocking() -> str | None:
    if sys.platform.startswith("win"):
        import msvcrt

        if not msvcrt.kbhit():
            return None
        key = msvcrt.getwch()
        if key == "\x1b":
            return "esc"
        return None

    import select
    import termios
    import tty

    if not sys.stdin.isatty():
        return None

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return None
        key = sys.stdin.read(1)
        if key == "\x1b":
            return "esc"
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def repair_incomplete_tool_history(history: list[dict[str, Any] | Any]) -> None:
    pending_call_ids: list[str] = []
    completed_call_ids: set[str] = set()

    for item in history:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        if item_type == "function_call":
            pending_call_ids.append(call_id)
        elif item_type == "function_call_output":
            completed_call_ids.add(call_id)

    for call_id in pending_call_ids:
        if call_id in completed_call_ids:
            continue
        history.append(build_function_call_output_item(call_id, "工具已中断"))
