import json
import threading
from typing import Any

import httpx
from openai import OpenAI
from core.common_output import COLORS, RESET, format_tool_call, print_box
from core.common_resources import TOOL_HANDLERS, TOOLS
from core.config_manager import load_agent_config
from core.slash_commands import handle_slash_command
from core.skill_manager import SkillManager

SKILL_MANAGER = SkillManager()
ALL_TOOLS = TOOLS + SKILL_MANAGER.get_tools()
ALL_HANDLERS = {**TOOL_HANDLERS, **SKILL_MANAGER.get_handlers()}


def normalize_tool_result(result: Any) -> tuple[str, str]:
    if isinstance(result, str):
        return result, result
    if isinstance(result, dict):
        output = result.get("output", "")
        display_result = result.get("display_result", output)
        return str(output), str(display_result)
    text = str(result)
    return text, text


def run_with_working_counter(callable_obj: Any) -> Any:
    stop_event = threading.Event()
    working_color = COLORS.get("user", "")

    def worker() -> None:
        seconds = 0
        while not stop_event.wait(1):
            seconds += 1
            print(
                f"\r{working_color}Working {seconds}s...{RESET}",
                end="",
                flush=True,
            )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        return callable_obj()
    finally:
        stop_event.set()
        thread.join(timeout=0.2)
        print()


def print_response_items(response: Any, history: list[Any]) -> list[Any]:
    tool_calls: list[Any] = []

    for item in response.output:
        if item.type != "reasoning":
            continue
        for summary_item in item.summary or []:
            text = getattr(summary_item, "text", "")
            if text:
                print_box("reason", text, title="REASON")
                history.append({"role": "assistant", "content": text})

    for item in response.output:
        if item.type != "message":
            continue
        for content_item in item.content:
            if getattr(content_item, "type", None) != "output_text":
                continue
            text = getattr(content_item, "text", "")
            if text:
                print_box("ai", text, title="AI")
                history.append({"role": "assistant", "content": text})

    for item in response.output:
        if item.type == "function_call":
            tool_calls.append(item)
            # history.append(ResponseFunctionToolCall(arguments=item.arguments, call_id=item.call_id, name=item.name, type="function_call"))
            history.append({
                "type": "function_call",
                "name": item.name,
                "arguments": item.arguments,
                "call_id": item.call_id,
            })

    return tool_calls


def run_tool_call(tool_call: Any) -> dict[str, str]:
    tool_name = tool_call.name
    arguments = json.loads(tool_call.arguments)
    print_box(
        "tool_calling",
        format_tool_call({"name": tool_name, "args": arguments}),
        title="Tool Calling",
    )
    handler = ALL_HANDLERS.get(tool_name)
    if handler is None:
        result: Any = f"Unknown tool: {tool_name}"
    else:
        try:
            result = handler(arguments)
        except Exception as exc:
            result = f"Tool '{tool_name}' failed: {exc}"

    output, display_result = normalize_tool_result(result)
    print_box("tool", display_result, title="Tool Result")
    # return FunctionCallOutput(call_id=tool_call.call_id, output=output, type="function_call_output")
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": output,
    }

def agent_loop(
    client: OpenAI,
    model: str,
    effort: str,
    history: list[dict[str, Any] | Any],
) -> None:
    while True:
        response = run_with_working_counter(
            lambda: client.responses.create(
                model=model,
                input=history,
                tools=ALL_TOOLS,
                reasoning={"effort": effort, "summary": "auto"},
            )
        )
        # history.extend(response.output)
        tool_calls = print_response_items(response, history)
        if not tool_calls:
            return

        tool_outputs = [run_tool_call(tool_call) for tool_call in tool_calls]
        history.extend(tool_outputs)


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

    skill_section = SKILL_MANAGER.build_system_section()
    system_prompt = (
        "你是一个agent。"
        "你可以调用工具来解决问题。"
        "在调用工具时，务必生成一段文字来说明你要做什么。"
    )
    if skill_section:
        system_prompt = f"{system_prompt}\n\n{skill_section}"

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
        agent_loop(client=client, model=config.model, effort=config.effort, history=history)


if __name__ == "__main__":
    main()
