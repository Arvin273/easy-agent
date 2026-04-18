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
from core.utils.history_items import (
    build_assistant_message,
    build_function_call_item,
    build_function_call_output_item,
)
from core.utils.session_runner_utils import (
    format_tool_output_preview,
    normalize_tool_result,
    read_cancel_key_nonblocking,
    repair_incomplete_tool_history,
    should_print_tool_output_preview,
)
from core.terminal.cli_output import (
    Colors,
    RESET,
    THEME,
    format_tool_call,
    print_marked_text,
    print_text,
)

def stream_response_with_working_counter(
        client: OpenAI,
        model: str,
        effort: str,
        prompt_cache_key: str,
        history: list[dict[str, Any] | Any],
        instructions: str,
        tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Any], bool]:
    # 以流式方式消费模型输出，实时打印文本增量，同时保留中断能力。
    done_event = threading.Event()
    cancel_event = threading.Event()
    output_started_event = threading.Event()
    working_color = Colors.reason
    error_holder: dict[str, BaseException] = {}
    previous_sigint_handler: Any = None
    sigint_handler_installed = False
    status_line_rendered = False
    started_at = time.monotonic()
    last_rendered_elapsed = -1
    active_stream: dict[str, Any] = {}
    active_block_key: dict[str, str | None] = {"value": None}
    active_block_kind: dict[str, str | None] = {"value": None}
    block_line_started: dict[str, bool] = {"value": False}
    streamed_message_items: dict[str, dict[str, Any]] = {}
    streamed_tool_calls: list[Any] = []
    stream_lock = threading.Lock()

    def _elapsed_seconds() -> int:
        return max(1, int(time.monotonic() - started_at))

    def _clear_status_line() -> None:
        nonlocal status_line_rendered
        if status_line_rendered and sys.stdout.isatty():
            print("\x1b[1A\x1b[2K\r", end="", flush=True)
            status_line_rendered = False
            return
        columns = shutil.get_terminal_size(fallback=(100, 20)).columns
        print(f"\r{' ' * max(1, columns - 1)}\r", end="", flush=True)

    def _render_status() -> None:
        nonlocal status_line_rendered, last_rendered_elapsed
        if output_started_event.is_set():
            return
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

    def _switch_stream_block(block_key: str, block_kind: str) -> None:
        if active_block_key["value"] == block_key:
            return
        if active_block_key["value"] is not None:
            sys.stdout.write("\n\n")
        marker_color = Colors.reason if block_kind == "reasoning" else Colors.ai
        body_color = Colors.reason if block_kind == "reasoning" else Colors.ai
        marker_prefix = "• "
        sys.stdout.write(
            f"{marker_color}{marker_prefix}{RESET}"
        )
        sys.stdout.flush()
        active_block_key["value"] = block_key
        active_block_kind["value"] = block_kind
        block_line_started["value"] = True

    def _append_stream_delta(block_key: str, block_kind: str, delta: str) -> None:
        if not delta:
            return
        with stream_lock:
            if not output_started_event.is_set():
                output_started_event.set()
                _clear_status_line()
            _switch_stream_block(block_key, block_kind)
            body_color = Colors.reason if block_kind == "reasoning" else Colors.ai
            continuation_prefix = "  "
            parts = delta.split("\n")
            for index, part in enumerate(parts):
                is_new_line = index > 0
                if is_new_line:
                    sys.stdout.write("\n")
                if part:
                    if is_new_line or not block_line_started["value"]:
                        sys.stdout.write(f"{body_color}{continuation_prefix}{part}{RESET}")
                    else:
                        sys.stdout.write(f"{body_color}{part}{RESET}")
                    block_line_started["value"] = True
                    continue
                if is_new_line and (index < len(parts) - 1 or not delta.endswith("\n")):
                    sys.stdout.write(f"{body_color}{continuation_prefix}{RESET}")
                block_line_started["value"] = False
            if delta.endswith("\n"):
                block_line_started["value"] = False
            sys.stdout.flush()

    def _finalize_stream_output() -> None:
        with stream_lock:
            if active_block_key["value"] is not None:
                sys.stdout.write("\n\n")
                sys.stdout.flush()
                active_block_key["value"] = None
                active_block_kind["value"] = None
                block_line_started["value"] = False

    def request_worker() -> None:
        try:
            with client.responses.stream(
                    model=model,
                    input=history,
                    instructions=instructions,
                    tools=tools,
                    reasoning={"effort": effort, "summary": "auto"},
                    prompt_cache_key=prompt_cache_key,
            ) as stream:
                active_stream["value"] = stream
                for event in stream:
                    if cancel_event.is_set():
                        break
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_text.delta":
                        message_key = f"message:{getattr(event, 'item_id', '')}:{getattr(event, 'content_index', 0)}"
                        _append_stream_delta(
                            message_key,
                            "message",
                            getattr(event, "delta", ""),
                        )
                        item_id = str(getattr(event, "item_id", "") or "")
                        content_index = int(getattr(event, "content_index", 0) or 0)
                        message_item = streamed_message_items.setdefault(
                            item_id,
                            {
                                "type": "message",
                                "role": "assistant",
                                "content_parts": {},
                                "output_index": int(getattr(event, "output_index", 0) or 0),
                            },
                        )
                        content_parts = message_item["content_parts"]
                        content_parts[content_index] = str(content_parts.get(content_index, "")) + str(
                            getattr(event, "delta", "")
                        )
                    elif event_type == "response.reasoning_summary_text.delta":
                        reasoning_key = f"reasoning:{getattr(event, 'item_id', '')}:{getattr(event, 'summary_index', 0)}"
                        _append_stream_delta(
                            reasoning_key,
                            "reasoning",
                            getattr(event, "delta", ""),
                        )
                    elif event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) == "reasoning":
                            continue
                    elif event_type == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) == "function_call":
                            streamed_tool_calls.append(item)
                if cancel_event.is_set():
                    try:
                        stream.close()
                    except Exception:
                        pass
        except BaseException as exc:  # noqa: BLE001
            error_holder["error"] = exc
        finally:
            _finalize_stream_output()
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
                stream = active_stream.get("value")
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                return [], [], True
            if done_event.wait(0.1):
                break
            _render_status()
            if read_cancel_key_nonblocking() == "esc":
                cancel_event.set()

        if "error" in error_holder:
            raise error_holder["error"]
        response_items_to_history: list[dict[str, Any]] = []
        for message_item in streamed_message_items.values():
            content_parts = message_item.pop("content_parts", {})
            content_text = "".join(
                str(content_parts[index])
                for index in sorted(content_parts)
            )
            if content_text:
                response_items_to_history.append(
                    {
                        **build_assistant_message(content_text),
                        "output_index": message_item.get("output_index", 0),
                    }
                )
        response_items_to_history.sort(key=lambda item: int(item.get("output_index", 0)))
        for item in response_items_to_history:
            item.pop("output_index", None)
        return response_items_to_history, streamed_tool_calls, False
    finally:
        if sigint_handler_installed:
            try:
                signal.signal(signal.SIGINT, previous_sigint_handler)
            except Exception:
                pass
        if not output_started_event.is_set():
            if status_line_rendered and sys.stdout.isatty():
                print("\x1b[1A\x1b[2K\r", end="", flush=True)
            else:
                columns = shutil.get_terminal_size(fallback=(100, 20)).columns
                print(f"\r{' ' * max(1, columns - 1)}\r", end="", flush=True)

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
    if should_print_tool_output_preview(tool_name, str(output)):
        preview = format_tool_output_preview(str(output), edge_lines=3)
        print_text(Colors.reason, f"{preview}\n")
        print()
    return build_function_call_output_item(tool_call.call_id, output)


def run_until_no_tool_call(
        client: OpenAI,
        model: str,
        effort: str,
        prompt_cache_key: str,
        token_threshold: int,
        keep_recent_messages_count: int,
        instructions: str,
        history: list[dict[str, Any] | Any],
        tools: list[dict[str, Any]],
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
) -> None:
    # 驱动一轮完整的 agent 交互，直到模型不再返回新的工具调用。
    while True:
        repair_incomplete_tool_history(history)
        # Auto-compaction by token threshold.
        if estimate_tokens(history, instructions) > token_threshold:
            print_text(Colors.reason, "Compacting...\n")
            history[:] = compact_history(
                client=client,
                model=model,
                history=history,
                keep_recent_messages_count=keep_recent_messages_count,
            )
            print_text(Colors.reason, "Compacted\n\n")

        response_items, streamed_tool_calls, cancelled = stream_response_with_working_counter(
            client=client,
            model=model,
            effort=effort,
            prompt_cache_key=prompt_cache_key,
            history=history,
            instructions=instructions,
            tools=tools,
        )
        if cancelled:
            print_text(Colors.error, "[Interrupted] 已中断本次生成。\n\n")
            return

        history.extend(response_items)
        for item in streamed_tool_calls:
            history.append(build_function_call_item(item.name, item.arguments, item.call_id))
        if not streamed_tool_calls:
            return

        tool_outputs: list[dict[str, str]] = []
        for tool_call in streamed_tool_calls:
            tool_outputs.append(run_tool_call(tool_call, handlers))

        history.extend(tool_outputs)

        if any(str(item.get("output", "")) == "工具已中断" for item in tool_outputs):
            return
