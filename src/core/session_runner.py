from __future__ import annotations

import json
import shutil
import sys
import threading
from typing import Any, Callable

from openai import OpenAI

from core.cli_output import COLORS, RESET, THEME, format_tool_call, print_box


def normalize_tool_result(result: Any) -> tuple[str, str]:
    if isinstance(result, str):
        return result, result
    if isinstance(result, dict):
        output = result.get("output", "")
        display_result = result.get("display_result", output)
        return str(output), str(display_result)
    text = str(result)
    return text, text


def _read_cancel_key_nonblocking() -> str | None:
    if sys.platform.startswith("win"):
        import msvcrt

        if not msvcrt.kbhit():
            return None
        key = msvcrt.getwch()
        if key == "\x1b":
            return "esc"
        return None

    import select
    import termios
    import tty

    if not sys.stdin.isatty():
        return None

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return None
        key = sys.stdin.read(1)
        if key == "\x1b":
            return "esc"
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def run_with_working_counter(callable_obj: Callable[[], Any]) -> tuple[Any | None, int, bool]:
    done_event = threading.Event()
    working_color = COLORS.get("user", "")
    counter = {"seconds": 0}
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}

    def request_worker() -> None:
        try:
            result_holder["value"] = callable_obj()
        except BaseException as exc:  # noqa: BLE001
            error_holder["error"] = exc
        finally:
            done_event.set()

    request_thread = threading.Thread(target=request_worker, daemon=True)
    request_thread.start()

    try:
        while True:
            if done_event.wait(1):
                break
            counter["seconds"] += 1
            print(
                f"\r{working_color}{THEME.body_indent}Generating {counter['seconds']}s... (Esc to cancel){RESET}",
                end="",
                flush=True,
            )
            if _read_cancel_key_nonblocking() == "esc":
                return None, max(1, counter["seconds"]), True

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value"), max(1, counter["seconds"]), False
    finally:
        columns = shutil.get_terminal_size(fallback=(100, 20)).columns
        print(f"\r{' ' * max(1, columns - 1)}\r", end="", flush=True)


def print_response_items(
    response: Any,
    history: list[Any],
    ai_title_suffix: str | None = None,
) -> list[Any]:
    tool_calls: list[Any] = []

    for item in response.output:
        if item.type != "reasoning":
            continue
        for summary_item in item.summary or []:
            text = getattr(summary_item, "text", "")
            if text:
                print_box("reason", text, title="REASON")

    for item in response.output:
        if item.type != "message":
            continue
        for content_item in item.content:
            if getattr(content_item, "type", None) != "output_text":
                continue
            text = getattr(content_item, "text", "")
            if text:
                print_box("ai", text, title="AI", title_suffix=ai_title_suffix)
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
    call_index: int | None = None,
) -> dict[str, str]:
    tool_name = tool_call.name
    arguments = json.loads(tool_call.arguments)
    call_title = "Tool Calling" if call_index is None else f"Tool Calling #{call_index}"
    print_box(
        "tool_calling",
        format_tool_call({"name": tool_name, "args": arguments}),
        title=call_title,
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
    result_title = "Tool Result" if call_index is None else f"Tool Result #{call_index}"
    print_box("tool", display_result, title=result_title)
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
        response, elapsed_seconds, cancelled = run_with_working_counter(
            lambda: client.responses.create(
                model=model,
                input=history,
                tools=tools,
                reasoning={"effort": effort, "summary": "auto"},
            )
        )
        if cancelled:
            print_box("user", "已中断本次生成（ESC）。", title="Interrupted")
            return

        ai_title_suffix = f"Generating {elapsed_seconds}s..."
        tool_calls = print_response_items(
            response,
            history,
            ai_title_suffix=ai_title_suffix,
        )
        if not tool_calls:
            return

        tool_outputs = [
            run_tool_call(tool_call, handlers, call_index=index)
            for index, tool_call in enumerate(tool_calls, start=1)
        ]
        history.extend(tool_outputs)
