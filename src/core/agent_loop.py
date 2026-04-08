import sys
import time
from typing import Any

import httpx
from openai import OpenAI
from core.config.config_manager import load_agent_config
from core.context.agents_instructions import load_agents_system_messages
from core.context.skill_manager import SkillManager
from core.session_runner import run_until_no_tool_call
from core.terminal.cli_output import ANSI_ENABLED, print_box, print_startup_banner
from core.commands import handle_slash_command
from core.tools import ToolRegistry

SKILL_MANAGER = SkillManager()
TOOL_REGISTRY = ToolRegistry(SKILL_MANAGER)


def build_system_prompt(skill_manager: SkillManager) -> str:
    skill_section = skill_manager.build_system_section()
    system_prompt = (
        "你是一个agent。"
        "你可以调用工具来解决问题。"
        "在调用工具时，务必生成一段文字来说明你要做什么。"
        "当你不确定下一步该怎么做时，优先调用 ask_user_question 向用户提问并等待选择。"
    )
    if skill_section:
        return f"{system_prompt}\n\n{skill_section}"
    return system_prompt


def refresh_tools_and_system_prompt(history: list[dict[str, Any] | Any]) -> None:
    changed = TOOL_REGISTRY.refresh()
    if not changed or not history:
        return
    first = history[0]
    if isinstance(first, dict) and first.get("role") == "system":
        first["content"] = build_system_prompt(SKILL_MANAGER)


def _is_agents_system_message(message: dict[str, Any] | Any) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("role") != "system":
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith("以下是来自") and "AGENTS.md 指令，请严格遵守：" in content


def refresh_agents_system_messages(history: list[dict[str, Any] | Any]) -> None:
    if not history:
        return
    base_message = history[:1]
    other_messages = [message for message in history[1:] if not _is_agents_system_message(message)]
    history[:] = [*base_message, *load_agents_system_messages(), *other_messages]


def agent_loop(
    client: OpenAI,
    model: str,
    effort: str,
    history: list[dict[str, Any] | Any],
) -> None:
    bundle = TOOL_REGISTRY.get_bundle()
    run_until_no_tool_call(
        client=client,
        model=model,
        effort=effort,
        history=history,
        tools=bundle.tools,
        handlers=bundle.handlers,
    )


def _clear_input_line(prompt: str, buffer_len: int) -> None:
    sys.stdout.write("\r")
    if ANSI_ENABLED:
        sys.stdout.write("\x1b[2K")
    else:
        sys.stdout.write(" " * (len(prompt) + buffer_len + 2))
        sys.stdout.write("\r")
    sys.stdout.write(prompt)
    sys.stdout.flush()


def _read_user_input_windows(prompt: str) -> str:
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    esc_pending = False
    last_esc_time = 0.0

    while True:
        ch = msvcrt.getwch()

        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buffer)
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            esc_pending = False
            continue
        if ch == "\x1b":
            now = time.monotonic()
            if esc_pending and (now - last_esc_time) <= 0.6:
                buffer_len = len(buffer)
                buffer = []
                esc_pending = False
                _clear_input_line(prompt, buffer_len)
            else:
                esc_pending = True
                last_esc_time = now
            continue

        esc_pending = False
        if ch in ("\b", "\x7f"):
            if buffer:
                buffer.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue

        buffer.append(ch)
        sys.stdout.write(ch)
        sys.stdout.flush()


def _read_user_input_posix(prompt: str) -> str:
    import termios
    import tty

    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    esc_pending = False
    last_esc_time = 0.0
    stdin = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin)
    try:
        tty.setraw(stdin)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x1b":
                now = time.monotonic()
                if esc_pending and (now - last_esc_time) <= 0.6:
                    buffer_len = len(buffer)
                    buffer = []
                    esc_pending = False
                    _clear_input_line(prompt, buffer_len)
                else:
                    esc_pending = True
                    last_esc_time = now
                continue

            esc_pending = False
            if ch in ("\x7f", "\b"):
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue

            buffer.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, old_settings)


def read_user_input(prompt: str) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)
    if sys.platform.startswith("win"):
        return _read_user_input_windows(prompt)
    return _read_user_input_posix(prompt)


def main() -> None:
    try:
        config = load_agent_config()
    except Exception as exc:
        print_box("error", str(exc), title="Config Error")
        return

    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=httpx.Client(verify=False),
    )
    print_startup_banner(
        model=config.model,
        effort=config.effort,
        directory=str(SKILL_MANAGER.workdir),
    )

    system_prompt = build_system_prompt(SKILL_MANAGER)

    history: list[dict[str, Any] | Any] = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *load_agents_system_messages(),
    ]
    while True:
        try:
            query = read_user_input("> ").strip()
            print()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.startswith("/"):
            should_exit = handle_slash_command(query, SKILL_MANAGER)
            if should_exit:
                break
            try:
                config = load_agent_config()
            except Exception as exc:
                print_box("error", f"配置重载失败: {exc}", title="Config Error")
            continue

        history.append({"role": "user", "content": query})
        refresh_tools_and_system_prompt(history)
        refresh_agents_system_messages(history)
        agent_loop(client=client, model=config.model, effort=config.effort, history=history)


if __name__ == "__main__":
    main()
