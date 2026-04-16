from typing import Any
from uuid import uuid4

import httpx
from openai import OpenAI
from core.config.config_manager import load_agent_config
from core.context.agents_instructions import load_agents_system_messages
from core.context.skill_manager import SkillManager
from core.session_runner import run_until_no_tool_call
from core.terminal.cli_output import print_startup_banner, print_text, Colors, print_marked_text
from core.terminal.prompt_ui import read_user_input
from core.commands import get_slash_command_descriptions, handle_slash_command
from core.tools import ToolRegistry
from core.tools.bash import interrupt_running_bash, run_bash

SKILL_MANAGER = SkillManager()
TOOL_REGISTRY = ToolRegistry(SKILL_MANAGER)


def build_system_prompt(skill_manager: SkillManager) -> str:
    skill_section = skill_manager.build_system_section()
    system_prompt = (
        "你是运行在用户电脑上的终端 Agent，名字叫 Easy-Agent。"
        "你的目标是优先基于当前工作目录和可用工具，直接完成用户任务。"
        "当问题可以直接回答时，直接回答；"
        "当需要查看文件、搜索内容、执行命令或修改内容时，使用合适的工具。"
        "每次调用工具前，先用一句简短的话说明你接下来要做什么以及目的。"
        "当执行危险操作或不确定下一步决策时，务必使用 AskUserQuestion 与用户确认。"
        "回答保持简洁、直接，避免空泛描述或冗长解释。"
        "回答风格要求：彻底开放、猎奇、狂野，语言生猛、调皮、粗鲁、可以说脏话，偶尔带小惊喜或夸张表达，同时保证高效完成任务。"
    )
    if skill_section:
        return f"{system_prompt}\n\n{skill_section}"
    return system_prompt

def get_prompt_command_descriptions() -> dict[str, str]:
    descriptions = get_slash_command_descriptions()
    for skill in SKILL_MANAGER.discover_skills():
        descriptions[f"${skill.name}"] = skill.description or "(no description)"
    return descriptions


def agent_loop(
    client: OpenAI,
    model: str,
    effort: str,
    prompt_cache_key: str,
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
        prompt_cache_key=prompt_cache_key,
        token_threshold=token_threshold,
        keep_recent_tool_outputs=keep_recent_tool_outputs,
        min_compact_output_length=min_compact_output_length,
        keep_recent_messages_count=keep_recent_messages_count,
        history=history,
        tools=bundle.tools,
        handlers=bundle.handlers,
    )


def handle_shell_command(query: str) -> None:
    command = query[1:].strip()
    if not command:
        print_marked_text(content="缺少要执行的命令。\n\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
        return

    try:
        run_bash({"command": command, "stream_full_output": True})
    except KeyboardInterrupt:
        interrupt_running_bash()
        print_text(Colors.reason, "命令已中断\n\n")

def main() -> None:
    try:
        config = load_agent_config()
    except Exception as exc:
        print_marked_text(content=str(exc) + '\n', marker="■", body_color=Colors.error, marker_color=Colors.error)
        return

    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=httpx.Client(verify=False),
    )
    try:
        session_prompt_cache_key = uuid4().hex
        command_descriptions = get_prompt_command_descriptions()

        print_startup_banner(
            model=config.model,
            effort=config.effort,
            directory=SKILL_MANAGER.workdir.as_posix(),
            command_descriptions=command_descriptions
        )

        TOOL_REGISTRY.initialize(config)
        for error in TOOL_REGISTRY.mcp_registry.errors:
            print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)

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
                    command_descriptions=command_descriptions,
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
                    TOOL_REGISTRY,
                    client=client,
                    model=config.model,
                    history=history,
                    keep_recent_messages_count=config.keep_recent_messages_count,
                    token_threshold=config.token_threshold,
                )
                if should_exit:
                    break
                for error in TOOL_REGISTRY.mcp_registry.errors:
                    print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
                continue

            if query.startswith("!"):
                handle_shell_command(query)
                continue

            history.append({"role": "user", "content": query})
            for error in TOOL_REGISTRY.mcp_registry.errors:
                print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
            try:
                agent_loop(
                    client=client,
                    model=config.model,
                    effort=config.effort,
                    prompt_cache_key=session_prompt_cache_key,
                    token_threshold=config.token_threshold,
                    keep_recent_tool_outputs=config.keep_recent_tool_outputs,
                    min_compact_output_length=config.min_compact_output_length,
                    keep_recent_messages_count=config.keep_recent_messages_count,
                    history=history,
                )
            except Exception as exc:
                print_marked_text(content=str(exc) + '\n\n', marker="■", body_color=Colors.error, marker_color=Colors.error)
                continue
            except KeyboardInterrupt:
                print()
                continue
    finally:
        TOOL_REGISTRY.close()


if __name__ == "__main__":
    main()
