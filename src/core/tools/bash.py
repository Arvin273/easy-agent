from __future__ import annotations

import codecs
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from itertools import count
from shutil import which
from typing import Any

from core.terminal.cli_output import ANSI_ENABLED, RESET, THEME, Colors, print_text
from core.tools.common import WORKDIR, parse_optional_int

DEFAULT_TIMEOUT_MS = 120_000
DEFAULT_BACKGROUND_TIMEOUT_MS = 600_000
MAX_TIMEOUT_MS = 600_000
MAX_OUTPUT_CHARS = 50_000
MAX_PREVIEW_CHARS = 12_000
PREVIEW_EDGE_LINES = 3

_ACTIVE_PROCESSES_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen[bytes]] = set()

_BACKGROUND_TASKS_LOCK = threading.Lock()
_BACKGROUND_TASKS: dict[str, "_BackgroundTaskState"] = {}
_BACKGROUND_TASK_COUNTER = count(1)


def _format_elapsed_seconds(seconds: float) -> str:
    return f"{seconds:.3f}s"


def _format_live_preview(text: str, edge_lines: int = 4) -> list[str]:
    lines = text.splitlines()
    max_lines = edge_lines * 2
    if len(lines) <= max_lines:
        return lines
    hidden = len(lines) - max_lines
    return lines[:edge_lines] + [f"... ({hidden} more lines)"] + lines[-edge_lines:]


def _coerce_timeout_ms(value: Any) -> int:
    timeout = parse_optional_int(value, "timeout")
    if timeout is None:
        return DEFAULT_TIMEOUT_MS
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0。")
    if timeout > MAX_TIMEOUT_MS:
        raise ValueError(f"timeout 不能超过 {MAX_TIMEOUT_MS} 毫秒。")
    return timeout


def _resolve_timeout_ms(value: Any, *, run_in_background: bool) -> int:
    if value is None:
        return DEFAULT_BACKGROUND_TIMEOUT_MS if run_in_background else DEFAULT_TIMEOUT_MS
    return _coerce_timeout_ms(value)


def _coerce_bool(value: Any, field_name: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} 参数必须是布尔值。")


def _build_bash_env() -> dict[str, str]:
    env = os.environ.copy()
    has_utf8_locale = False
    for env_name in ("LC_ALL", "LANG"):
        env_value = env.get(env_name, "").strip().lower()
        if "utf-8" in env_value or "utf8" in env_value:
            has_utf8_locale = True
            break
    if not has_utf8_locale:
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"
    return env


class _TerminalOutputNormalizer:
    def __init__(self) -> None:
        self._current_line = ""
        self._pending_carriage_return = False
        self._escape_buffer = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""

        normalized_parts: list[str] = []
        for char in text:
            if self._escape_buffer:
                self._escape_buffer += char
                if self._consume_escape_buffer():
                    continue
                if len(self._escape_buffer) > 32:
                    self._escape_buffer = ""
                continue

            if self._pending_carriage_return:
                if char == "\n":
                    normalized_parts.append(self._current_line)
                    normalized_parts.append("\n")
                    self._current_line = ""
                    self._pending_carriage_return = False
                    continue
                self._current_line = ""
                self._pending_carriage_return = False

            if char == "\r":
                self._pending_carriage_return = True
                continue
            if char == "\x1b":
                self._escape_buffer = char
                continue
            if char == "\b":
                self._current_line = self._current_line[:-1]
                continue
            if char == "\n":
                normalized_parts.append(self._current_line)
                normalized_parts.append("\n")
                self._current_line = ""
                continue
            self._current_line += char

        return "".join(normalized_parts)

    def flush(self) -> str:
        self._pending_carriage_return = False
        self._escape_buffer = ""
        if not self._current_line:
            return ""
        tail = self._current_line
        self._current_line = ""
        return tail

    def _consume_escape_buffer(self) -> bool:
        if self._escape_buffer == "\x1b":
            return True
        if not self._escape_buffer.startswith("\x1b["):
            self._escape_buffer = ""
            return False

        suffix = self._escape_buffer[-1]
        if suffix.isalpha():
            parameter_text = self._escape_buffer[2:-1]
            self._apply_csi(parameter_text, suffix)
            self._escape_buffer = ""
            return True
        return True

    def _apply_csi(self, parameter_text: str, command: str) -> None:
        params = [part for part in parameter_text.split(";") if part]
        if command == "K":
            if not params or params[0] in {"0", "2"}:
                self._current_line = ""
            return

        count = 1
        if params:
            try:
                count = max(int(params[0]), 0)
            except ValueError:
                return
        if command == "D":
            self._current_line = self._current_line[:-count]
        elif command == "C":
            self._current_line += " " * count


@lru_cache(maxsize=1)
def _resolve_bash_executable() -> str:
    if sys.platform.startswith("win"):
        where_result = subprocess.run(
            ["where", "bash"],
            cwd=WORKDIR,
            capture_output=True,
            timeout=10,
            check=False,
        )
        for raw_line in where_result.stdout.splitlines():
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                return line
    else:
        bash_path = which("bash")
        if bash_path:
            return bash_path
    raise RuntimeError("Error: 未找到 bash 可执行文件。")


def _start_bash_process(command: str) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {
        "cwd": WORKDIR,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 0,
        "env": _build_bash_env(),
    }
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([_resolve_bash_executable(), "-lc", command], **kwargs)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            cwd=WORKDIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, 15)
    except ProcessLookupError:
        return
    except Exception:
        process.kill()
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError:
            return


class _OutputBuffer:
    def __init__(self, max_output_chars: int = MAX_OUTPUT_CHARS, max_preview_chars: int = MAX_PREVIEW_CHARS) -> None:
        self._lock = threading.Lock()
        self._max_output_chars = max_output_chars
        self._max_preview_chars = max_preview_chars
        self._output_parts: list[str] = []
        self._output_len = 0
        self._output_truncated = False
        self._preview_parts: list[str] = []
        self._preview_len = 0
        self._preview_truncated = False
        self._preview_head = ""
        self._preview_tail = ""

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._append_output(text)
            self._append_preview(text)

    def get_output(self) -> str:
        with self._lock:
            text = "".join(self._output_parts)
            if self._output_truncated:
                text += "\n[output truncated]"
            return text

    def get_preview_text(self) -> str:
        with self._lock:
            if not self._preview_truncated:
                return "".join(self._preview_parts)
            return f"{self._preview_head}\n... [preview truncated] ...\n{self._preview_tail}"

    def _append_output(self, text: str) -> None:
        if self._output_truncated:
            return
        remaining = self._max_output_chars - self._output_len
        if remaining <= 0:
            self._output_truncated = True
            return
        chunk = text[:remaining]
        self._output_parts.append(chunk)
        self._output_len += len(chunk)
        if len(chunk) < len(text):
            self._output_truncated = True

    def _append_preview(self, text: str) -> None:
        if not self._preview_truncated and self._preview_len + len(text) <= self._max_preview_chars:
            self._preview_parts.append(text)
            self._preview_len += len(text)
            return

        if not self._preview_truncated:
            combined = "".join(self._preview_parts) + text
            keep = self._max_preview_chars // 2
            self._preview_head = combined[:keep]
            self._preview_tail = combined[-keep:]
            self._preview_parts.clear()
            self._preview_truncated = True
            return

        keep = self._max_preview_chars // 2
        self._preview_tail = (self._preview_tail + text)[-keep:]


class _LiveBashPreview:
    def __init__(self, output_buffer: _OutputBuffer, started_at: float) -> None:
        self._lock = threading.Lock()
        self._buffer = output_buffer
        self._rendered_lines = 0
        self._started_at = started_at
        self._enabled = sys.stdout.isatty() and ANSI_ENABLED
        self._plain_text_buffer = ""

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            if self._enabled:
                self._render()
            else:
                self._plain_text_buffer += text
                self._flush_plain_text_lines()

    def tick(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._render()

    def finalize(self) -> None:
        if not self._enabled:
            with self._lock:
                if self._plain_text_buffer:
                    print_text(Colors.reason, self._plain_text_buffer)
                    self._plain_text_buffer = ""
            if self._buffer.get_preview_text():
                sys.stdout.write("\n")
                sys.stdout.flush()
            return
        with self._lock:
            if self._rendered_lines:
                sys.stdout.write("\n")
                sys.stdout.flush()

    def _render(self) -> None:
        preview_lines = _format_live_preview(self._buffer.get_preview_text(), edge_lines=PREVIEW_EDGE_LINES)
        elapsed_line = f"[elapsed: {_format_elapsed_seconds(time.time() - self._started_at)}]"
        display_lines = [elapsed_line, *preview_lines]
        for _ in range(self._rendered_lines):
            sys.stdout.write("\x1b[1A\x1b[2K\r")

        for line in display_lines:
            sys.stdout.write(f"{Colors.reason}{THEME.body_indent}{line}{RESET}\n")
        sys.stdout.flush()
        self._rendered_lines = len(display_lines)

    def _flush_plain_text_lines(self) -> None:
        while True:
            newline_index = self._plain_text_buffer.find("\n")
            if newline_index < 0:
                return
            line = self._plain_text_buffer[: newline_index + 1]
            print_text(Colors.reason, line)
            self._plain_text_buffer = self._plain_text_buffer[newline_index + 1 :]


@dataclass
class _BackgroundTaskState:
    task_id: str
    command: str
    description: str
    started_at: float
    process: subprocess.Popen[bytes]
    output_buffer: _OutputBuffer = field(default_factory=_OutputBuffer)
    status: str = "running"
    return_code: int | None = None
    finished_at: float | None = None
    timeout_ms: int = DEFAULT_BACKGROUND_TIMEOUT_MS

    def snapshot(self, include_output: bool = False) -> dict[str, Any]:
        elapsed_seconds = (self.finished_at or time.time()) - self.started_at
        preview = self.output_buffer.get_preview_text().strip()
        data = {
            "task_id": self.task_id,
            "command": self.command,
            "description": self.description,
            "status": self.status,
            "return_code": self.return_code,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
            "finished_at": (
                datetime.fromtimestamp(self.finished_at).isoformat(timespec="seconds")
                if self.finished_at is not None
                else None
            ),
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
        output = self.output_buffer.get_output().strip()
        data["preview"] = preview
        if include_output:
            data["output"] = output
        return data


def _read_process_output(
    process: subprocess.Popen[bytes],
    output_buffer: _OutputBuffer,
    live_preview: _LiveBashPreview | None = None,
) -> None:
    pipe = process.stdout
    if pipe is None:
        return

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    normalizer = _TerminalOutputNormalizer()

    try:
        while True:
            data = pipe.read(4096)
            if not data:
                break
            text = decoder.decode(data)
            if text:
                normalized = normalizer.feed(text)
                if normalized:
                    output_buffer.append(normalized)
                    if live_preview is not None:
                        live_preview.append(normalized)
        tail = decoder.decode(b"", final=True)
        if tail:
            normalized_tail = normalizer.feed(tail)
            if normalized_tail:
                output_buffer.append(normalized_tail)
                if live_preview is not None:
                    live_preview.append(normalized_tail)
        final_tail = normalizer.flush()
        if final_tail:
            output_buffer.append(final_tail)
            if live_preview is not None:
                live_preview.append(final_tail)
    finally:
        pipe.close()


def interrupt_running_bash() -> bool:
    interrupted = False
    with _ACTIVE_PROCESSES_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        try:
            _terminate_process_tree(process)
            interrupted = True
        except Exception:
            continue
    return interrupted


def _run_foreground_process(
    process: subprocess.Popen[bytes],
    timeout_ms: int,
) -> str:
    started_at = time.time()
    output_buffer = _OutputBuffer()
    preview = _LiveBashPreview(output_buffer, started_at)
    reader_thread = threading.Thread(
        target=_read_process_output,
        args=(process, output_buffer, preview),
        daemon=True,
    )
    stop_preview_event = threading.Event()
    tick_thread = threading.Thread(
        target=_tick_live_preview,
        args=(preview, stop_preview_event),
        daemon=True,
    )

    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.add(process)

    reader_thread.start()
    tick_thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
    finally:
        stop_preview_event.set()
        with _ACTIVE_PROCESSES_LOCK:
            _ACTIVE_PROCESSES.discard(process)
        reader_thread.join(timeout=2)
        tick_thread.join(timeout=1)
        preview.finalize()

    if timed_out:
        seconds = timeout_ms / 1000
        preview = output_buffer.get_preview_text().strip()
        if preview:
            return f"Error: Timeout ({seconds:g}s)\n\nPreview:\n{preview}"
        return f"Error: Timeout ({seconds:g}s)"

    output = output_buffer.get_output().strip()
    return output if output else "(no output)"


def _tick_live_preview(preview: _LiveBashPreview, stop_event: threading.Event) -> None:
    while not stop_event.wait(0.2):
        preview.tick()


def _monitor_background_task(task_id: str) -> None:
    with _BACKGROUND_TASKS_LOCK:
        task = _BACKGROUND_TASKS.get(task_id)
    if task is None:
        return

    reader_thread = threading.Thread(
        target=_read_process_output,
        args=(task.process, task.output_buffer, None),
        daemon=True,
    )
    reader_thread.start()
    timed_out = False
    try:
        task.process.wait(timeout=task.timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(task.process)
    reader_thread.join(timeout=2)

    with _BACKGROUND_TASKS_LOCK:
        current = _BACKGROUND_TASKS.get(task_id)
        if current is None:
            return
        if current.status == "cancelled":
            current.finished_at = current.finished_at or time.time()
            current.return_code = current.return_code if current.return_code is not None else task.process.returncode
            return
        current.return_code = task.process.returncode
        current.finished_at = time.time()
        if timed_out:
            current.status = "timed_out"
        elif task.process.returncode == 0:
            current.status = "completed"
        else:
            current.status = "failed"


def _start_background_task(command: str, description: str, timeout_ms: int) -> str:
    process = _start_bash_process(command)
    task_id = f"bash-{next(_BACKGROUND_TASK_COUNTER)}"
    state = _BackgroundTaskState(
        task_id=task_id,
        command=command,
        description=description,
        started_at=time.time(),
        process=process,
        timeout_ms=timeout_ms,
    )
    with _BACKGROUND_TASKS_LOCK:
        _BACKGROUND_TASKS[task_id] = state
    monitor_thread = threading.Thread(target=_monitor_background_task, args=(task_id,), daemon=True)
    monitor_thread.start()
    return task_id


def stop_background_bash_task(task_id: str) -> str:
    with _BACKGROUND_TASKS_LOCK:
        task = _BACKGROUND_TASKS.get(task_id)
        if task is None:
            return f"Error: 未找到后台 Bash 任务 {task_id}"
        if task.status != "running":
            return f"Background bash task {task_id} is already {task.status}"
        task.status = "cancelled"
        task.finished_at = time.time()

    _terminate_process_tree(task.process)
    try:
        task.return_code = task.process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        task.return_code = task.process.returncode
    return f"Cancelled background bash task {task_id}"


def get_background_bash_tasks(
    *,
    task_id: str | None = None,
    status: str | None = None,
    include_output: bool = False,
) -> list[dict[str, Any]]:
    with _BACKGROUND_TASKS_LOCK:
        tasks = list(_BACKGROUND_TASKS.values())

    if task_id is not None:
        tasks = [task for task in tasks if task.task_id == task_id]
    if status is not None:
        tasks = [task for task in tasks if task.status == status]

    tasks.sort(key=lambda task: task.started_at)
    snapshots = [task.snapshot(include_output=include_output) for task in tasks]
    return snapshots


def run_bash(arguments: dict[str, Any]) -> str:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少有效的 command 参数。")

    description_value = arguments.get("description")
    description = command.strip()
    if description_value is not None:
        if not isinstance(description_value, str):
            raise ValueError("description 参数必须是字符串。")
        if description_value.strip():
            description = description_value.strip()

    run_in_background = _coerce_bool(arguments.get("run_in_background"), "run_in_background")
    timeout_ms = _resolve_timeout_ms(arguments.get("timeout"), run_in_background=run_in_background)

    try:
        if run_in_background:
            task_id = _start_background_task(command, description, timeout_ms)
            return f"Started background bash task {task_id}"
        process = _start_bash_process(command)
    except RuntimeError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error: {exc}"

    return _run_foreground_process(process, timeout_ms)


def run_bash_jobs(arguments: dict[str, Any]) -> str:
    task_id = arguments.get("task_id")
    status = arguments.get("status")
    include_output = _coerce_bool(arguments.get("include_output"), "include_output")

    if task_id is not None and not isinstance(task_id, str):
        raise ValueError("task_id 参数必须是字符串。")
    if status is not None:
        if not isinstance(status, str):
            raise ValueError("status 参数必须是字符串。")
        if status not in {"running", "completed", "failed", "timed_out", "cancelled"}:
            raise ValueError("status 只能是 running、completed、failed、timed_out 或 cancelled。")

    tasks = get_background_bash_tasks(
        task_id=task_id.strip() if isinstance(task_id, str) and task_id.strip() else None,
        status=status,
        include_output=include_output,
    )
    return json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2)


def run_bash_stop(arguments: dict[str, Any]) -> str:
    task_id = arguments.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("缺少有效的 task_id 参数。")
    return stop_background_bash_task(task_id.strip())


TOOL_NAME = "Bash"
TOOL_HANDLER = run_bash
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
        "description": (
            "执行一条 bash 命令，并返回输出。"
            "工作目录固定为当前项目目录。"
            "支持可选的 timeout（毫秒，前台默认 120000，后台默认 600000，最大 600000）、description 和 run_in_background。"
            "涉及查文件、读文件、写文件、搜索内容时，优先使用专门工具，不要滥用 Bash。"
        ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 bash 命令"},
            "timeout": {"type": "number", "description": "可选超时时间，单位毫秒"},
            "description": {"type": "string", "description": "命令用途说明，便于终端展示和后台任务查看"},
            "run_in_background": {"type": "boolean", "description": "是否作为后台任务启动，默认 false"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}

JOBS_TOOL_NAME = "BashJobs"
JOBS_TOOL_HANDLER = run_bash_jobs
JOBS_TOOL_DEF = {
    "type": "function",
    "name": JOBS_TOOL_NAME,
    "description": "查询后台 Bash 任务状态。可列出所有任务，也可按 task_id 或 status 过滤，并可选择返回完整输出。",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "可选，指定后台任务 ID，例如 bash-1"},
            "status": {
                "type": "string",
                "enum": ["running", "completed", "failed", "timed_out", "cancelled"],
                "description": "可选，按任务状态过滤",
            },
            "include_output": {"type": "boolean", "description": "是否返回完整输出，默认 false"},
        },
        "additionalProperties": False,
    },
}

STOP_TOOL_NAME = "BashStop"
STOP_TOOL_HANDLER = run_bash_stop
STOP_TOOL_DEF = {
    "type": "function",
    "name": STOP_TOOL_NAME,
    "description": "取消指定的后台 Bash 任务。若任务已结束，会直接返回当前状态，不报错。",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "要取消的后台任务 ID，例如 bash-1"},
        },
        "required": ["task_id"],
        "additionalProperties": False,
    },
}
