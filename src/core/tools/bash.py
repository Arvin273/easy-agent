import subprocess
import sys
import threading
from shutil import which
from typing import Any

from core.terminal.cli_output import ANSI_ENABLED, COLORS, RESET, THEME, print_text
from core.tools.common import WORKDIR

_ACTIVE_PROCESSES_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen[bytes]] = set()


def _format_live_preview(text: str, edge_lines: int = 4) -> list[str]:
    lines = text.splitlines()
    max_lines = edge_lines * 2
    if len(lines) <= max_lines:
        return lines
    hidden = len(lines) - max_lines
    return lines[:edge_lines] + [f"... ({hidden} more lines)"] + lines[-edge_lines:]


class _LiveBashPreview:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._parts: list[str] = []
        self._rendered_lines = 0
        self._enabled = sys.stdout.isatty() and ANSI_ENABLED

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._parts.append(text)
            if self._enabled:
                self._render()
            else:
                print_text("reason", text)

    def finalize(self) -> None:
        if not self._enabled:
            if self._parts:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return
        with self._lock:
            if self._rendered_lines:
                sys.stdout.write("\n")
                sys.stdout.flush()

    def get_output(self) -> str:
        with self._lock:
            return "".join(self._parts)

    def _render(self) -> None:
        preview_lines = _format_live_preview("".join(self._parts))
        for _ in range(self._rendered_lines):
            sys.stdout.write("\x1b[1A\x1b[2K\r")

        color = COLORS.get("reason", "")
        for line in preview_lines:
            sys.stdout.write(f"{color}{THEME.body_indent}{line}{RESET}\n")
        sys.stdout.flush()
        self._rendered_lines = len(preview_lines)


def interrupt_running_bash() -> bool:
    interrupted = False
    with _ACTIVE_PROCESSES_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        try:
            process.kill()
            interrupted = True
        except Exception:
            continue
    return interrupted


def run_bash(arguments: dict[str, Any]) -> str:
    def decode_console_output(data: bytes) -> str:
        for encoding in ("utf-8", "gbk", "cp936"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def resolve_bash_executable() -> str:
        if sys.platform.startswith("win"):
            where_result = subprocess.run(
                ["where", "bash"],
                cwd=WORKDIR,
                capture_output=True,
                timeout=10,
            )
            lines = [
                line.strip()
                for line in decode_console_output(where_result.stdout).splitlines()
                if line.strip()
            ]
            if lines:
                return lines[0]
        else:
            bash_path = which("bash")
            if bash_path:
                return bash_path
        raise RuntimeError("Error: Unable to locate bash executable")

    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少有效的 command 参数。")

    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command blocked"

    try:
        bash_executable = resolve_bash_executable()
        process = subprocess.Popen(
            [bash_executable, "-lc", command],
            cwd=WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except RuntimeError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error: {exc}"

    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.add(process)

    preview = _LiveBashPreview()

    def stream_pipe(pipe: Any) -> None:
        try:
            while True:
                reader = getattr(pipe, "read1", None)
                if callable(reader):
                    data = reader(1024)
                else:
                    data = pipe.read(1024)
                if not data:
                    break
                text = decode_console_output(data)
                preview.append(text)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stdout,),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stderr,),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
    finally:
        with _ACTIVE_PROCESSES_LOCK:
            _ACTIVE_PROCESSES.discard(process)

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)

    if timed_out:
        return "Error: Timeout (120s)"

    output = preview.get_output().strip()
    preview.finalize()
    return output[:50000] if output else "(no output)"


TOOL_NAME = "bash"
TOOL_HANDLER = run_bash
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "在工作区内执行一个 shell 命令，并返回标准输出和标准错误输出。",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}
