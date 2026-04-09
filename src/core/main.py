from typing import Any

import httpx
from openai import OpenAI
from core.config.config_manager import load_agent_config
from core.context.agents_instructions import load_agents_system_messages
from core.context.skill_manager import SkillManager
from core.session_runner import run_until_no_tool_call
from core.terminal.cli_output import print_title_and_content, print_startup_banner, print_text, Colors
from core.terminal.prompt_ui import read_user_input
from core.commands import get_slash_command_descriptions, handle_slash_command
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
    token_threshold: int,
    keep_recent_tool_outputs: int,
    min_compact_output_length: int,
    keep_recent_messages_count: int,
    history: list[dict[str, Any] | Any],
) -> None:
    bundle = TOOL_REGISTRY.get_bundle()
    run_until_no_tool_call(
        client=client,
        model=model,
        effort=effort,
        token_threshold=token_threshold,
        keep_recent_tool_outputs=keep_recent_tool_outputs,
        min_compact_output_length=min_compact_output_length,
        keep_recent_messages_count=keep_recent_messages_count,
        history=history,
        tools=bundle.tools,
        handlers=bundle.handlers,
    )


def main() -> None:
    try:
        config = load_agent_config()
    except Exception as exc:
        print_text(Colors.error, content=str(exc) + '\n')
        return

    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=httpx.Client(verify=False),
    )
    print_startup_banner(
        model=config.model,
        effort=config.effort,
        directory=SKILL_MANAGER.workdir.as_posix(),
        command_descriptions=get_slash_command_descriptions(),
    )

    system_prompt = build_system_prompt(SKILL_MANAGER)

    history: list[dict[str, Any] | Any] = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *load_agents_system_messages(),
    ]
    input_history: list[str] = []
    while True:
        try:
            query = read_user_input(
                "> ",
                history=input_history,
                command_descriptions=get_slash_command_descriptions(),
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query:
            input_history.append(query)
        else:
            continue

        if query.startswith("/"):
            should_exit = handle_slash_command(
                query,
                SKILL_MANAGER,
                client=client,
                model=config.model,
                history=history,
                keep_recent_messages_count=config.keep_recent_messages_count,
                token_threshold=config.token_threshold,
            )
            if should_exit:
                break
            try:
                config = load_agent_config()
            except Exception as exc:
                print_text(Colors.error, content=str(exc) + '\n')
            continue

        history.append({"role": "user", "content": query})
        refresh_tools_and_system_prompt(history)
        refresh_agents_system_messages(history)
        try:
            agent_loop(
                client=client,
                model=config.model,
                effort=config.effort,
                token_threshold=config.token_threshold,
                keep_recent_tool_outputs=config.keep_recent_tool_outputs,
                min_compact_output_length=config.min_compact_output_length,
                keep_recent_messages_count=config.keep_recent_messages_count,
                history=history,
            )
        except KeyboardInterrupt:
            print()
            continue


if __name__ == "__main__":
    main()

# TODO: TodoWrite subagents backgroundtask
