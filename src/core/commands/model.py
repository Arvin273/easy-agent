from __future__ import annotations

import json
import sys
from pathlib import Path

from core.config.config_manager import CONFIG_PATH, DEFAULT_EFFORT, DEFAULT_MODEL
from core.terminal.cli_output import THEME, print_title_and_content, print_text

COMMAND = "/model"
DESCRIPTION = "切换模型与推理强度"

MODEL_OPTIONS = [
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5.3-codex",
    "gpt-5.1-codex-max",
]

EFFORT_OPTIONS = ["none", "minimal", "low", "medium", "high", "xhigh"]


def _read_selection_key() -> str:
    if sys.platform.startswith("win"):
        import msvcrt

        while True:
            key = msvcrt.getwch()
            if key in ("\r", "\n"):
                return "enter"
            if key == "\x1b":
                return "cancel"
            if key in ("\x00", "\xe0"):
                arrow = msvcrt.getwch()
                if arrow == "H":
                    return "up"
                if arrow == "P":
                    return "down"
                continue
            if key.lower() == "k":
                return "up"
            if key.lower() == "j":
                return "down"
            if key == "\x03":
                raise KeyboardInterrupt
    else:
        import termios
        import tty
        import select

        stdin = sys.stdin.fileno()
        old_settings = termios.tcgetattr(stdin)
        try:
            tty.setraw(stdin)
            while True:
                key = sys.stdin.read(1)
                if key == "\x03":
                    raise KeyboardInterrupt
                if key in ("\r", "\n"):
                    return "enter"
                if key == "\x1b":
                    ready, _, _ = select.select([sys.stdin], [], [], 0.03)
                    if not ready:
                        return "cancel"
                    second = sys.stdin.read(1)
                    if second != "[":
                        return "cancel"
                    ready, _, _ = select.select([sys.stdin], [], [], 0.03)
                    if not ready:
                        return "cancel"
                    third = sys.stdin.read(1)
                    if second == "[" and third == "A":
                        return "up"
                    if second == "[" and third == "B":
                        return "down"
                    return "cancel"
                if key.lower() == "k":
                    return "up"
                if key.lower() == "j":
                    return "down"
        finally:
            termios.tcsetattr(stdin, termios.TCSADRAIN, old_settings)


def _render_select_list(options: list[str], selected: int) -> int:
    lines: list[str] = []
    for index, option in enumerate(options):
        marker = ">" if index == selected else " "
        lines.append(f"{THEME.body_indent}{marker} {option}")
    print("\n".join(lines), flush=True)
    return len(lines)


def _move_cursor_up(lines: int) -> None:
    if lines <= 0:
        return
    for _ in range(lines):
        print("\x1b[1A\x1b[2K", end="", flush=True)


def _select_from_options(title: str, prompt: str, options: list[str], default_index: int = 0) -> str:
    if not options:
        raise ValueError("options 不能为空。")
    if default_index < 0 or default_index >= len(options):
        default_index = 0

    print_title_and_content("ai", prompt, title=title)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return options[default_index]

    selected = default_index
    rendered_lines = _render_select_list(options, selected)
    while True:
        key = _read_selection_key()
        if key == "enter":
            print()
            return options[selected]
        if key == "cancel":
            print()
            raise KeyboardInterrupt
        if key == "up":
            selected = (selected - 1) % len(options)
        if key == "down":
            selected = (selected + 1) % len(options)
        _move_cursor_up(rendered_lines)
        rendered_lines = _render_select_list(options, selected)


def _load_config_payload(config_path: Path = CONFIG_PATH) -> dict[str, str]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "api_key": "",
                    "base_url": "",
                    "model": DEFAULT_MODEL,
                    "effort": DEFAULT_EFFORT,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("配置文件格式错误：根节点必须是对象。")
    return payload


def _save_config_payload(payload: dict[str, str], config_path: Path = CONFIG_PATH) -> None:
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def handle() -> bool:
    try:
        payload = _load_config_payload()
    except Exception as exc:
        print_text("error", f"读取配置失败: {exc}\n")
        return False

    current_model = str(payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    current_effort = str(payload.get("effort") or DEFAULT_EFFORT).strip() or DEFAULT_EFFORT

    model_candidates = list(dict.fromkeys([current_model, *MODEL_OPTIONS]))
    effort_candidates = list(dict.fromkeys([current_effort, *EFFORT_OPTIONS]))

    try:
        model = _select_from_options(
            title="Model Selector",
            prompt=f"当前模型: {current_model}\n使用 ↑/↓ 选择模型，按 Enter 确认，Esc/Ctrl+C 取消。",
            options=model_candidates,
            default_index=model_candidates.index(current_model),
        )

        effort = _select_from_options(
            title="Effort Selector",
            prompt=f"当前推理强度: {current_effort}\n使用 ↑/↓ 选择推理强度，按 Enter 确认，Esc/Ctrl+C 取消。",
            options=effort_candidates,
            default_index=effort_candidates.index(current_effort),
        )
    except KeyboardInterrupt:
        return False

    payload["model"] = model
    payload["effort"] = effort

    try:
        _save_config_payload(payload)
    except Exception as exc:
        print_text("error", f"保存配置失败: {exc}\n")
        return False

    print_title_and_content("ai", f"已切换配置:\nmodel: {model}\neffort: {effort}", title="Model Updated")
    return False
