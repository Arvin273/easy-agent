from typing import Any

import httpx
from openai import OpenAI
from core.cli_output import print_box
from core.config_manager import load_agent_config
from core.session_runner import run_until_no_tool_call
from core.slash_commands import handle_slash_command
from core.skill_manager import SkillManager
from core.tool_registry import ToolRegistry

SKILL_MANAGER = SkillManager()
TOOL_REGISTRY = ToolRegistry(SKILL_MANAGER)


def build_system_prompt(skill_manager: SkillManager) -> str:
    skill_section = skill_manager.build_system_section()
    system_prompt = (
        "你是一个agent。"
        "你可以调用工具来解决问题。"
        "在调用工具时，务必生成一段文字来说明你要做什么。"
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

    system_prompt = build_system_prompt(SKILL_MANAGER)

    history: list[dict[str, Any] | Any] = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]
    while True:
        try:
            query = input("> ").strip()
            print()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.startswith("/"):
            should_exit = handle_slash_command(query, SKILL_MANAGER)
            if should_exit:
                break
            continue

        history.append({"role": "user", "content": query})
        refresh_tools_and_system_prompt(history)
        agent_loop(client=client, model=config.model, effort=config.effort, history=history)


if __name__ == "__main__":
    main()

