from __future__ import annotations

import json
import threading
from typing import Any, Callable

from openai import OpenAI

from core.cli_output import COLORS, RESET, format_tool_call, print_box


def normalize_tool_result(result: Any) -> tuple[str, str]:
    if isinstance(result, str):
        return result, result
    if isinstance(result, dict):
        output = result.get("output", "")
        display_result = result.get("display_result", output)
        return str(output), str(display_result)
    text = str(result)
    return text, text


def run_with_working_counter(callable_obj: Callable[[], Any]) -> Any:
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
            history.append(
                {
                    "type": "function_call",
                    "name": item.name,
                    "arguments": item.arguments,
                    "call_id": item.call_id,
                }
            )

    return tool_calls


def run_tool_call(
    tool_call: Any,
    handlers: dict[str, Callable[[dict[str, Any]], Any]],
) -> dict[str, str]:
    tool_name = tool_call.name
    arguments = json.loads(tool_call.arguments)
    print_box(
        "tool_calling",
        format_tool_call({"name": tool_name, "args": arguments}),
        title="Tool Calling",
    )
    handler = handlers.get(tool_name)
    if handler is None:
        result: Any = f"Unknown tool: {tool_name}"
    else:
        try:
            result = handler(arguments)
        except Exception as exc:
            result = f"Tool '{tool_name}' failed: {exc}"

    output, display_result = normalize_tool_result(result)
    print_box("tool", display_result, title="Tool Result")
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": output,
    }


def run_until_no_tool_call(
    client: OpenAI,
    model: str,
    effort: str,
    history: list[dict[str, Any] | Any],
    tools: list[dict[str, Any]],
    handlers: dict[str, Callable[[dict[str, Any]], Any]],
) -> None:
    while True:
        response = run_with_working_counter(
            lambda: client.responses.create(
                model=model,
                input=history,
                tools=tools,
                reasoning={"effort": effort, "summary": "auto"},
            )
        )
        tool_calls = print_response_items(response, history)
        if not tool_calls:
            return

        tool_outputs = [run_tool_call(tool_call, handlers) for tool_call in tool_calls]
        history.extend(tool_outputs)

