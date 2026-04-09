import json
import os
import random
import shutil
import sys
import textwrap
import unicodedata
from importlib import metadata as importlib_metadata
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
    "white": "\033[37m" if ANSI_ENABLED else "",
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
SLASH_HINTS = (
    "/help 查看可用命令",
    "/skills 查看已安装技能",
    "/model 切换模型与推理强度",
    "/compact 手动压缩当前会话上下文",
    "/exit 退出会话",
)


def _resolve_version(default: str = "0.0.2") -> str:
    package_name = "easy-agent"
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        pass
    except Exception:
        return default

    pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if not pyproject_path.exists():
        return default

    try:
        import tomllib  # py>=3.11
    except Exception:
        return default

    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        version = data.get("project", {}).get("version")
        return str(version) if version else default
    except Exception:
        return default


def _random_slash_hint(command_descriptions: dict[str, str] | None = None) -> str:
    if command_descriptions:
        dynamic_hints = [
            f"{command} {description}".rstrip()
            for command, description in sorted(command_descriptions.items())
        ]
        if dynamic_hints:
            return random.choice(dynamic_hints)
    return random.choice(SLASH_HINTS)


def _char_display_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    # CJK/Wide/Full-width chars usually occupy 2 columns in terminal.
    if unicodedata.east_asian_width(ch) in {"W", "F"}:
        return 2
    return 1


def _display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)


def _fit_display_width(text: str, max_width: int) -> tuple[str, int]:
    if max_width <= 0:
        return "", 0
    out: list[str] = []
    width = 0
    for ch in str(text):
        ch_w = _char_display_width(ch)
        if width + ch_w > max_width:
            break
        out.append(ch)
        width += ch_w
    return "".join(out), width


def format_tool_call(tool_call: dict[str, Any]) -> str:
    name = str(tool_call.get("name", "unknown"))
    args = tool_call.get("args", {})
    if not args:
        return f"tool_name: {name}"

    try:
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
    except TypeError:
        args_text = str(args)

    arg_lines = args_text.splitlines()
    if len(arg_lines) > 8:
        hidden = len(arg_lines) - 8
        args_text = "\n".join(arg_lines[:4] + [f"... ({hidden} more lines)"] + arg_lines[-4:])

    return f"tool_name: {name}\nparameters:\n{args_text}"


def _resolve_line_width(columns: int) -> int:
    suggested = int(columns * THEME.width_ratio)
    return max(THEME.min_width, min(THEME.max_width, suggested))


def _wrap_text(text: str, width: int) -> str:
    lines = str(text).splitlines() or [""]
    return "\n".join(f"{THEME.body_indent}{line}" if line else "" for line in lines)


def print_title_and_content(
    role: str,
    content: str | None = None,
    title: str | None = None,
    title_suffix: str | None = None,
) -> None:
    color = COLORS.get(role, "")
    header = title or ROLE_LABELS.get(role, role.upper())
    columns = shutil.get_terminal_size(fallback=(100, 20)).columns
    safe_columns = max(20, columns - 2)
    line_width = min(safe_columns, _resolve_line_width(columns))
    max_header_len = max(1, line_width - 2)
    display_header = header[:max_header_len]
    suffix = f" {title_suffix}" if title_suffix else ""
    top = f"{THEME.body_indent}[{display_header}]{suffix}"
    body = _wrap_text(content, line_width)

    print(f"{color}{top}{RESET}")
    print(body)


def print_text(role: str, content: str) -> None:
    text = str(content or "")
    if not text:
        return

    color = COLORS.get(role, "")
    lines = text.splitlines(keepends=True)
    if not lines:
        return

    for line in lines:
        parts = line.split("\r")
        for index, part in enumerate(parts):
            if index > 0:
                sys.stdout.write("\r")
            if part:
                sys.stdout.write(f"{color}{THEME.body_indent}{part}{RESET}")
        if line.endswith("\n"):
            sys.stdout.flush()

    sys.stdout.flush()


def print_marked_text(
    role: str,
    content: str,
    marker: str,
    marker_role: str | None = None,
    body_role: str | None = None,
) -> None:
    text = str(content or "").rstrip()
    if not text:
        return

    marker_color = COLORS.get(marker_role or role, "")
    body_color = COLORS.get(role, "") if body_role is None else COLORS.get(body_role, "")
    lines = text.splitlines()
    marker_prefix = f"{marker} "
    continuation_prefix = " " * len(marker_prefix)

    for index, line in enumerate(lines):
        prefix = marker_prefix if index == 0 else continuation_prefix
        if index == 0:
            sys.stdout.write(f"{marker_color}{prefix}{RESET}{body_color}{line}{RESET}\n")
        else:
            sys.stdout.write(f"{body_color}{continuation_prefix}{line}{RESET}\n")

    sys.stdout.write("\n")
    sys.stdout.flush()


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


def print_startup_banner(
    model: str,
    effort: str,
    directory: str,
    version: str | None = None,
    command_descriptions: dict[str, str] | None = None,
) -> None:
    display_version = (version or "").strip() or _resolve_version()
    columns = shutil.get_terminal_size(fallback=(100, 20)).columns
    available_width = max(32, columns - len(THEME.body_indent))
    box_width = min(max(THEME.banner_max_width, 64), available_width)
    inner_width = max(20, box_width - 4)
    border_color = COLORS.get("reason", "")
    key_color = COLORS.get("reason", "")
    value_color = COLORS.get("white", "")
    accent_color = COLORS.get("ai", "")

    title = "Easy Agent"
    subtitle = f"v{display_version}"
    title_text = f"{title}  {subtitle}"
    detail_lines = (
        ("Model", f"{model} ({effort})"),
        ("Path", _display_directory(directory)),
        ("Hint", _random_slash_hint(command_descriptions)),
    )

    top_border = f"╭{'─' * (box_width - 2)}╮"
    divider = f"├{'─' * (box_width - 2)}┤"
    bottom_border = f"╰{'─' * (box_width - 2)}╯"

    print(f"{THEME.body_indent}{border_color}{top_border}{RESET}")
    title_display, title_w = _fit_display_width(title_text, inner_width)
    title_display = title_display + (" " * max(0, inner_width - title_w))
    print(f"{THEME.body_indent}{border_color}│{RESET} {accent_color}{title_display}{RESET} {border_color}│{RESET}")
    print(f"{THEME.body_indent}{border_color}{divider}{RESET}")

    for key, value in detail_lines:
        key_text = f"{key:<5}: "
        key_part, key_w = _fit_display_width(key_text, inner_width)
        value_space = max(0, inner_width - key_w)
        value_part, value_w = _fit_display_width(str(value), value_space)
        line_pad = max(0, inner_width - key_w - value_w)
        print(
            f"{THEME.body_indent}{border_color}│{RESET} "
            f"{key_color}{key_part}{RESET}{value_color}{value_part}{RESET}{' ' * line_pad} "
            f"{border_color}│{RESET}"
        )
    print(f"{THEME.body_indent}{border_color}{bottom_border}{RESET}")
    print()
