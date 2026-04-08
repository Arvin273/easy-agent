from __future__ import annotations

import json
import signal
import shutil
import sys
import threading
from typing import Any, Callable

from openai import OpenAI

import core.tools.bash as bash_tool
from core.context.compression import (
    compact_history,
    estimate_tokens,
    micro_compact,
)
from core.terminal.cli_output import (
    COLORS,
    RESET,
    THEME,
    format_tool_call,
    print_box,
    print_stream_text,
)


def normalize_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        output = result.get("output", "")
        return str(output)
    return str(result)


def _format_tool_output_preview(output: str, max_lines: int = 10) -> str:
    lines = output.splitlines()
    if len(lines) <= max_lines:
        return output
    hidden = len(lines) - max_lines
    preview_lines = lines[:max_lines] + [f"... ({hidden} more lines)"]
    return "\n".join(preview_lines)


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
    cancel_event = threading.Event()
    working_color = COLORS.get("user", "")
    counter = {"ticks": 0}
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}
    previous_sigint_handler: Any = None
    sigint_handler_installed = False

    def request_worker() -> None:
        try:
            result_holder["value"] = callable_obj()
        except BaseException as exc:  # noqa: BLE001
            error_holder["error"] = exc
        finally:
            done_event.set()

    request_thread = threading.Thread(target=request_worker, daemon=True)
    request_thread.start()

    def _on_sigint(signum: int, frame: Any) -> None:
        cancel_event.set()

    if threading.current_thread() is threading.main_thread():
        try:
            previous_sigint_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _on_sigint)
            sigint_handler_installed = True
        except Exception:
            sigint_handler_installed = False

    try:
        print(
            f"\r{working_color}{THEME.body_indent}Generating 0s... (Esc to cancel){RESET}",
            end="",
            flush=True,
        )
        while True:
            if cancel_event.is_set():
                return None, max(1, counter["ticks"] // 10), True
            if done_event.wait(0.1):
                break
            counter["ticks"] += 1
            if counter["ticks"] % 10 == 0:
                elapsed = counter["ticks"] // 10
                print(
                    f"\r{working_color}{THEME.body_indent}Generating {elapsed}s... (Esc to cancel){RESET}",
                    end="",
                    flush=True,
                )
            if _read_cancel_key_nonblocking() == "esc":
                return None, max(1, counter["ticks"] // 10), True

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value"), max(1, counter["ticks"] // 10), False
    finally:
        if sigint_handler_installed:
            try:
                signal.signal(signal.SIGINT, previous_sigint_handler)
            except Exception:
                pass
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
                print_stream_text("reason", f"Thinking: {text}\n\n")

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
    handlers: dict[str, Callable[[dict[str, Any]], Any]]
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
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, BaseException] = {}
        done_event = threading.Event()

        def tool_worker() -> None:
            try:
                result_holder["value"] = handler(arguments)
            except BaseException as exc:  # noqa: BLE001
                error_holder["error"] = exc
            finally:
                done_event.set()

        tool_thread = threading.Thread(target=tool_worker, daemon=True)
        tool_thread.start()

        interrupted = False
        warned_not_interruptible = False
        while True:
            if done_event.wait(0.1):
                break
            if _read_cancel_key_nonblocking() == "esc":
                if tool_name == "bash":
                    interrupted = True
                    bash_tool.interrupt_running_bash()
                    break
                if not warned_not_interruptible:
                    print_stream_text("reason", "当前工具不支持中断，等待执行完成...\n")
                    warned_not_interruptible = True

        if interrupted:
            print_stream_text("reason", "工具已中断\n\n")
            return {
                "type": "function_call_output",
                "call_id": tool_call.call_id,
                "output": "工具已中断",
            }

        if "error" in error_holder:
            result = f"Tool '{tool_name}' failed: {error_holder['error']}"
        else:
            result = result_holder.get("value")

    output = normalize_tool_result(result)
    if str(output) == "工具已中断":
        print_stream_text("reason", "工具已中断\n\n")
        return {
            "type": "function_call_output",
            "call_id": tool_call.call_id,
            "output": "工具已中断",
        }
    if tool_name != "bash" and str(output).strip():
        preview = _format_tool_output_preview(str(output), max_lines=10)
        print_stream_text("reason", f"{preview}\n")
        print()
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": output,
    }


def run_until_no_tool_call(
    client: OpenAI,
    model: str,
    effort: str,
    token_threshold: int,
    keep_recent_tool_outputs: int,
    min_compact_output_length: int,
    history: list[dict[str, Any] | Any],
    tools: list[dict[str, Any]],
    handlers: dict[str, Callable[[dict[str, Any]], Any]],
) -> None:
    while True:
        # Layer 1: lightweight compaction before each model call.
        micro_compact(
            history,
            keep_recent_tool_outputs=keep_recent_tool_outputs,
            min_compact_output_length=min_compact_output_length,
        )
        # Layer 2: auto-compaction by token threshold.
        if estimate_tokens(history) > token_threshold:
            print_stream_text("reason", "Compacting...\n")
            history[:] = compact_history(client=client, model=model, history=history)
            print_stream_text("reason", "Compacted\n\n")

        response, elapsed_seconds, cancelled = run_with_working_counter(
            lambda: client.responses.create(
                model=model,
                input=history,
                tools=tools,
                reasoning={"effort": effort, "summary": "auto"},
            )
        )
        if cancelled:
            print_stream_text("error", "[Interrupted] 已中断本次生成。\n\n")
            return

        ai_title_suffix = f"Generating {elapsed_seconds}s..."
        tool_calls = print_response_items(
            response,
            history,
            ai_title_suffix=ai_title_suffix,
        )
        if not tool_calls:
            return

        tool_outputs: list[dict[str, str]] = []
        manual_compact = False
        manual_focus: str | None = None
        for index, tool_call in enumerate(tool_calls, start=1):
            if tool_call.name == "compact":
                manual_compact = True
                try:
                    compact_args = json.loads(tool_call.arguments)
                except Exception:
                    compact_args = {}
                focus_val = compact_args.get("focus")
                if isinstance(focus_val, str) and focus_val.strip():
                    manual_focus = focus_val.strip()
                continue
            tool_outputs.append(run_tool_call(tool_call, handlers))

        history.extend(tool_outputs)
        # Layer 3: model-triggered manual compaction.
        if manual_compact:
            print_stream_text("reason", "Compacting...\n")
            history[:] = compact_history(client=client, model=model, history=history, focus=manual_focus)
            print_stream_text("reason", "Compacted\n\n")
            return

        if any(str(item.get("output", "")) == "工具已中断" for item in tool_outputs):
            return
