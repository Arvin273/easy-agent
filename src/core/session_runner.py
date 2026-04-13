from __future__ import annotations

import json
import signal
import shutil
import sys
import threading
from typing import Any, Callable

from openai import OpenAI

import core.tools.bash as bash_tool
from core.tools.bash import TOOL_NAME as BASH_TOOL_NAME
from core.context.compression import (
    compact_history,
    estimate_tokens,
    micro_compact,
)
from core.terminal.cli_output import (
    Colors,
    RESET,
    THEME,
    format_tool_call,
    print_marked_text,
    print_text,
)


def normalize_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        output = result.get("output", "")
        return str(output)
    return str(result)


def _truncate_preview_line(line: str, max_width: int = 160) -> str:
    if len(line) <= max_width:
        return line
    hidden = len(line) - max_width
    return f"{line[:max_width]}... ({hidden} more chars)"


def _format_tool_output_preview(output: str, edge_lines: int = 4) -> str:
    lines = output.splitlines()
    if len(lines) <= 1:
        try:
            parsed = json.loads(output)
        except Exception:
            parsed = None
        if parsed is not None:
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            lines = pretty.splitlines()
    lines = [_truncate_preview_line(line) for line in lines]
    max_lines = edge_lines * 2
    if len(lines) <= max_lines:
        return "\n".join(lines)
    hidden = len(lines) - max_lines
    preview_lines = lines[:edge_lines] + [f"... ({hidden} more lines)"] + lines[-edge_lines:]
    return "\n".join(preview_lines)


def _should_print_tool_output_preview(tool_name: str, output: str) -> bool:
    stripped = str(output).strip()
    if not stripped:
        return False
    if tool_name != BASH_TOOL_NAME:
        return True
    return (
        stripped.startswith("Error:")
        or stripped == "(no output)"
        or stripped.startswith("Started background bash task ")
    )


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
    working_color = Colors.reason
    counter = {"ticks": 0}
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}
    previous_sigint_handler: Any = None
    sigint_handler_installed = False
    status_line_rendered = False

    def _render_status(elapsed: int) -> None:
        nonlocal status_line_rendered
        status_text = (
            f"{working_color}{THEME.body_indent}Generating {elapsed}s... (Esc to cancel){RESET}"
        )
        if sys.stdout.isatty():
            if not status_line_rendered:
                print(f"{status_text}\n", end="", flush=True)
                status_line_rendered = True
            else:
                print(f"\x1b[1A\x1b[2K\r{status_text}\n", end="", flush=True)
            return
        print(f"\r{status_text}", end="", flush=True)

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
        _render_status(0)
        while True:
            if cancel_event.is_set():
                return None, max(1, counter["ticks"] // 10), True
            if done_event.wait(0.1):
                break
            counter["ticks"] += 1
            if counter["ticks"] % 10 == 0:
                _render_status(counter["ticks"] // 10)
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
        if status_line_rendered and sys.stdout.isatty():
            print("\x1b[1A\x1b[2K\r", end="", flush=True)
        else:
            columns = shutil.get_terminal_size(fallback=(100, 20)).columns
            print(f"\r{' ' * max(1, columns - 1)}\r", end="", flush=True)


def print_response_items(
    response: Any,
    history: list[Any],
) -> list[Any]:
    tool_calls: list[Any] = []

    for item in response.output:
        if item.type != "reasoning":
            continue
        for summary_item in item.summary or []:
            text = getattr(summary_item, "text", "")
            if text:
                print_marked_text(
                    f"Thinking: {text}",
                    marker="•",
                    marker_color=Colors.reason,
                    body_color=Colors.reason,
                )

    for item in response.output:
        if item.type != "message":
            continue
        for content_item in item.content:
            if getattr(content_item, "type", None) != "output_text":
                continue
            text = getattr(content_item, "text", "")
            if text:
                print_marked_text(
                    text,
                    marker="•",
                    marker_color=Colors.ai,
                    body_color=Colors.ai,
                )
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
    print_marked_text(
        format_tool_call({"name": tool_name, "args": arguments}),
        marker="•",
        marker_color=Colors.green,
        body_color=Colors.simple,
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
                if tool_name == BASH_TOOL_NAME:
                    interrupted = True
                    bash_tool.interrupt_running_bash()
                    break
                if not warned_not_interruptible:
                    print_text(Colors.reason, "当前工具不支持中断，等待执行完成...\n\n")
                    warned_not_interruptible = True

        if interrupted:
            print_text(Colors.reason, "工具已中断\n\n")
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
        print_text(Colors.reason, "工具已中断\n\n")
        return {
            "type": "function_call_output",
            "call_id": tool_call.call_id,
            "output": "工具已中断",
        }
    if _should_print_tool_output_preview(tool_name, str(output)):
        preview = _format_tool_output_preview(str(output), edge_lines=3)
        print_text(Colors.reason, f"{preview}\n")
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
    keep_recent_messages_count: int,
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
            print_text(Colors.reason, "Compacting...\n")
            history[:] = compact_history(
                client=client,
                model=model,
                history=history,
                keep_recent_messages_count=keep_recent_messages_count,
            )
            print_text(Colors.reason, "Compacted\n\n")

        response, elapsed_seconds, cancelled = run_with_working_counter(
            lambda: client.responses.create(
                model=model,
                input=history,
                tools=tools,
                reasoning={"effort": effort, "summary": "auto"},
                store=True
            )
        )
        if cancelled:
            print_text(Colors.error, "[Interrupted] 已中断本次生成。\n\n")
            return

        tool_calls = print_response_items(
            response,
            history,
        )
        if not tool_calls:
            return

        tool_outputs: list[dict[str, str]] = []
        for tool_call in tool_calls:
            tool_outputs.append(run_tool_call(tool_call, handlers))

        history.extend(tool_outputs)

        if any(str(item.get("output", "")) == "工具已中断" for item in tool_outputs):
            return
