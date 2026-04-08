import json
import os
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config.config_manager import PATHS


def _ansi_enabled() -> bool:
    value = os.getenv("NO_COLOR", "").strip().lower()
    return value in {"", "0", "false", "no"}


ANSI_ENABLED = _ansi_enabled()
RESET = "\033[0m" if ANSI_ENABLED else ""
COLORS = {
    "ai": "\033[32m" if ANSI_ENABLED else "",
    "tool": "\033[34m" if ANSI_ENABLED else "",
    "tool_calling": "\033[33m" if ANSI_ENABLED else "",
    "error": "\033[31m" if ANSI_ENABLED else "",
    "user": "\033[36m" if ANSI_ENABLED else "",
    "reason": "\033[90m" if ANSI_ENABLED else "",
}

ROLE_LABELS = {
    "ai": "AI",
    "tool": "TOOL",
    "tool_calling": "TOOL CALL",
    "error": "ERROR",
    "user": "USER",
    "reason": "REASON",
}


@dataclass(frozen=True)
class OutputTheme:
    border_char: str = "─"
    body_indent: str = "  "
    width_ratio: float = 0.85
    min_width: int = 40
    max_width: int = 100
    banner_max_width: int = 50


THEME = OutputTheme()


def format_tool_call(tool_call: dict[str, Any]) -> str:
    name = str(tool_call.get("name", "unknown"))
    args = tool_call.get("args", {})
    if not args:
        return f"调用工具: {name}"

    try:
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
    except TypeError:
        args_text = str(args)

    arg_lines = args_text.splitlines()
    if len(arg_lines) > 8:
        hidden = len(arg_lines) - 8
        args_text = "\n".join(arg_lines[:8] + [f"... ({hidden} more lines)"])

    return f"调用工具: {name}\n参数:\n{args_text}"


def _resolve_line_width(columns: int) -> int:
    suggested = int(columns * THEME.width_ratio)
    return max(THEME.min_width, min(THEME.max_width, suggested))


def _wrap_text(text: str, width: int) -> str:
    body_width = max(10, width - len(THEME.body_indent))
    wrapped_lines: list[str] = []
    for raw_line in str(text).splitlines() or [""]:
        if not raw_line.strip():
            wrapped_lines.append("")
            continue
        chunks = textwrap.wrap(
            raw_line,
            width=body_width,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(chunks or [raw_line])
    return "\n".join(f"{THEME.body_indent}{line}" if line else "" for line in wrapped_lines)


def print_box(
    role: str,
    content: str,
    title: str | None = None,
    title_suffix: str | None = None,
) -> None:
    text = str(content or "").strip()
    if not text:
        return

    color = COLORS.get(role, "")
    header = title or ROLE_LABELS.get(role, role.upper())
    columns = shutil.get_terminal_size(fallback=(100, 20)).columns
    safe_columns = max(20, columns - 2)
    line_width = min(safe_columns, _resolve_line_width(columns))
    max_header_len = max(1, line_width - 2)
    display_header = header[:max_header_len]
    suffix = f" {title_suffix}" if title_suffix else ""
    top = f"{THEME.body_indent}[{display_header}]{suffix}"
    body = _wrap_text(text, line_width)

    print(f"{color}{top}{RESET}")
    print(body)
    print()


def _display_directory(path_text: str) -> str:
    try:
        path = Path(path_text).resolve()
        home = PATHS.home
        path_str = str(path)
        home_str = str(home)
        if path_str == home_str:
            return "~"
        if path_str.startswith(home_str + os.sep):
            return "~" + path_str[len(home_str):]
        return path_text
    except Exception:
        return path_text


def print_startup_banner(model: str, effort: str, directory: str, version: str = "0.0.2") -> None:
    columns = shutil.get_terminal_size(fallback=(100, 20)).columns
    available_width = max(20, columns - len(THEME.body_indent))
    box_width = min(THEME.banner_max_width, available_width)
    inner_width = max(10, box_width - 4)
    border_color = COLORS.get("reason", "")
    text_color = COLORS.get("user", "")

    line1 = f">_ Easy Agent (v{version})"
    line2 = f"model:     {model} {effort}     /model to change"
    line3 = f"directory: {_display_directory(directory)}"

    if box_width < 16:
        for line in (line1, line2, line3):
            print(f"{THEME.body_indent}{line}")
        print()
        return

    print(f"{THEME.body_indent}{border_color}┌{'─' * (box_width - 2)}┐{RESET}")
    for line in (line1, "", line2, line3):
        display = line[:inner_width].ljust(inner_width)
        print(f"{THEME.body_indent}{border_color}│{RESET} {text_color}{display}{RESET} {border_color}│{RESET}")
    print(f"{THEME.body_indent}{border_color}└{'─' * (box_width - 2)}┘{RESET}")
    print()
