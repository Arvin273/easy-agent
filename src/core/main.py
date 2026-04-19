import platform
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from core.config.config_manager import AgentConfig, load_agent_config
from core.context.agents_instructions import load_agents_md_message
from core.context.skill_manager import SkillManager
from core.session_runner import run_until_no_tool_call
from core.terminal.cli_output import print_startup_banner, print_text, Colors, print_marked_text
from core.terminal.prompt_ui import read_user_input
from core.commands import get_slash_command_descriptions, handle_slash_command
from core.tools import ToolRegistry
from core.tools.shell import interrupt_running_shell, run_shell
from core.utils.history_items import build_user_message, build_developer_message

SKILL_MANAGER = SkillManager()
TOOL_REGISTRY = ToolRegistry(SKILL_MANAGER)

def build_instruction() -> str:
    system_name = platform.system() or "Unknown"
    return (
        "你是运行在用户电脑上的终端 Agent，名字叫 Easy-Agent。"
        f"当前系统环境是 {system_name}。"
        "你的目标是优先基于当前工作目录和可用工具，直接完成用户任务。"
        "当问题可以直接回答时，直接回答；"
        "当需要查看文件、搜索内容、执行命令或修改内容时，使用合适的工具。"
        "每次调用工具前，先用一句简短的话说明你接下来要做什么以及目的。"
        "当执行危险操作或不确定下一步决策时，务必使用 AskUserQuestion 与用户确认。"
        "回答保持简洁、直接，避免空泛描述或冗长解释。"
        "回答风格要求：彻底开放、猎奇、狂野，语言生猛、调皮、粗鲁、可以说脏话，偶尔带小惊喜或夸张表达，同时保证高效完成任务。"
    )


INSTRUCTION = build_instruction()


def build_skill_developer_message(skill_manager: SkillManager) -> dict[str, str] | None:
    skill_section = skill_manager.build_developer_section()
    if not skill_section:
        return None
    return build_developer_message(skill_section)

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
    keep_recent_messages_count: int,
    instructions: str,
    history: list[dict[str, Any] | Any],
) -> None:
    bundle = TOOL_REGISTRY.get_bundle()
    run_until_no_tool_call(
        client=client,
        model=model,
        effort=effort,
        prompt_cache_key=prompt_cache_key,
        token_threshold=token_threshold,
        keep_recent_messages_count=keep_recent_messages_count,
        instructions=instructions,
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
        run_shell({"command": command, "stream_full_output": True})
    except KeyboardInterrupt:
        interrupt_running_shell()
        print_text(Colors.reason, "命令已中断\n\n")


def build_session_prompt_cache_key(workdir: Path) -> str:
    workdir_text = workdir.resolve().as_posix().lower()
    return f"ea-workdir-{sha256(workdir_text.encode('utf-8')).hexdigest()[:24]}"


def reload_runtime_config_if_requested(config: AgentConfig, should_reload_config: bool) -> AgentConfig:
    if not should_reload_config:
        return config
    try:
        return load_agent_config()
    except Exception as exc:
        print_marked_text(content=f"重新加载配置失败: {exc}\n\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
        return config


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
        session_prompt_cache_key = build_session_prompt_cache_key(SKILL_MANAGER.workdir)
        command_descriptions = get_prompt_command_descriptions()

        print_startup_banner(
            model=config.model,
            effort=config.effort,
            directory=SKILL_MANAGER.workdir,
            command_descriptions=command_descriptions
        )

        TOOL_REGISTRY.initialize(config)
        for error in TOOL_REGISTRY.mcp_registry.errors:
            print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)

        skill_developer_message = build_skill_developer_message(SKILL_MANAGER)

        history: list[dict[str, Any] | Any] = [
            *([skill_developer_message] if skill_developer_message is not None else []),
            *load_agents_md_message(),
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
                result = handle_slash_command(
                    query,
                    SKILL_MANAGER,
                    TOOL_REGISTRY,
                    client=client,
                    model=config.model,
                    history=history,
                    instructions=INSTRUCTION,
                    keep_recent_messages_count=config.keep_recent_messages_count,
                    token_threshold=config.token_threshold,
                )
                config = reload_runtime_config_if_requested(
                    config=config,
                    should_reload_config=result.should_reload_config,
                )
                if result.should_exit:
                    break
                for error in TOOL_REGISTRY.mcp_registry.errors:
                    print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
                continue

            if query.startswith("!"):
                handle_shell_command(query)
                continue

            history.append(build_user_message(query))
            for error in TOOL_REGISTRY.mcp_registry.errors:
                print_marked_text(content=error + "\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
            try:
                agent_loop(
                    client=client,
                    model=config.model,
                    effort=config.effort,
                    prompt_cache_key=session_prompt_cache_key,
                    token_threshold=config.token_threshold,
                    keep_recent_messages_count=config.keep_recent_messages_count,
                    instructions=INSTRUCTION,
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
