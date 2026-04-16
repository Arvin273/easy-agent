from __future__ import annotations

import json
import signal
import shutil
import sys
import threading
import time
from typing import Any, Callable

from openai import OpenAI

import core.tools.bash as bash_tool
from core.tools.bash import TOOL_NAME as BASH_TOOL_NAME
from core.context.compression import (
    compact_history,
    estimate_tokens,
)
from core.utils.session_runner_utils import (
    format_tool_output_preview,
    normalize_tool_result,
    read_cancel_key_nonblocking,
    repair_incomplete_tool_history,
)
from core.terminal.cli_output import (
    Colors,
    RESET,
    THEME,
    format_tool_call,
    print_marked_text,
    print_text,
)


def _should_print_tool_output_preview(tool_name: str, output: str) -> bool:
    # Bash 只在错误、无输出或转后台时打印摘要，避免正常命令刷屏。
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


def run_with_working_counter(callable_obj: Callable[[], Any]) -> tuple[Any | None, int, bool]:
    # 在请求模型期间持续刷新状态，并支持 Esc/Ctrl+C 取消本轮生成。
    done_event = threading.Event()
    cancel_event = threading.Event()
    working_color = Colors.reason
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}
    previous_sigint_handler: Any = None
    sigint_handler_installed = False
    status_line_rendered = False
    started_at = time.monotonic()
    last_rendered_elapsed = -1

    def _elapsed_seconds() -> int:
        return max(1, int(time.monotonic() - started_at))

    def _render_status() -> None:
        nonlocal status_line_rendered, last_rendered_elapsed
        elapsed = _elapsed_seconds()
        if elapsed == last_rendered_elapsed:
            return
        last_rendered_elapsed = elapsed
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
        _render_status()
        while True:
            if cancel_event.is_set():
                return None, _elapsed_seconds(), True
            if done_event.wait(0.1):
                break
            _render_status()
            if read_cancel_key_nonblocking() == "esc":
                return None, _elapsed_seconds(), True

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value"), _elapsed_seconds(), False
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
    # 统一打印模型输出，并把 assistant 消息和 function_call 写回 history。
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
    # 执行单次工具调用，负责终端展示、中断处理和 function_call_output 封装。
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

        warned_not_interruptible = False
        interrupted = False
        previous_sigint_handler: Any = None
        sigint_handler_installed = False
        sigint_received = False

        def _on_sigint(signum: int, frame: Any) -> None:
            nonlocal sigint_received
            sigint_received = True

        if threading.current_thread() is threading.main_thread():
            try:
                previous_sigint_handler = signal.getsignal(signal.SIGINT)
                signal.signal(signal.SIGINT, _on_sigint)
                sigint_handler_installed = True
            except Exception:
                sigint_handler_installed = False

        try:
            while True:
                if done_event.wait(0.1):
                    break
                cancel_requested = sigint_received or read_cancel_key_nonblocking() == "esc"
                if not cancel_requested:
                    continue
                if tool_name == BASH_TOOL_NAME:
                    bash_tool.interrupt_running_bash()
                    print_text(Colors.reason, "工具已中断\n\n")
                    interrupted = True
                    break
                if not warned_not_interruptible:
                    print_text(Colors.reason, "当前工具不支持中断，等待执行完成...\n\n")
                    warned_not_interruptible = True
        finally:
            if sigint_handler_installed:
                try:
                    signal.signal(signal.SIGINT, previous_sigint_handler)
                except Exception:
                    pass

        if interrupted:
            result = "工具已中断"
        elif "error" in error_holder:
            result = f"Tool '{tool_name}' failed: {error_holder['error']}"
        else:
            result = result_holder.get("value")

    output = normalize_tool_result(result)
    if _should_print_tool_output_preview(tool_name, str(output)):
        preview = format_tool_output_preview(str(output), edge_lines=3)
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
        prompt_cache_key: str,
        token_threshold: int,
        keep_recent_messages_count: int,
        history: list[dict[str, Any] | Any],
        tools: list[dict[str, Any]],
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
) -> None:
    # 驱动一轮完整的 agent 交互，直到模型不再返回新的工具调用。
    while True:
        repair_incomplete_tool_history(history)
        # Auto-compaction by token threshold.
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
                store=True,
                prompt_cache_key=prompt_cache_key,
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
