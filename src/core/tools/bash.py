import subprocess
import sys
import threading
from shutil import which
from typing import Any

from core.terminal.cli_output import print_stream_text
from core.tools.common import WORKDIR

_ACTIVE_PROCESSES_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen[bytes]] = set()


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

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def stream_pipe(pipe: Any, chunks: list[str]) -> None:
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
                chunks.append(text)
                print_stream_text("reason", text)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stdout, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stderr, stderr_chunks),
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

    if stdout_chunks or stderr_chunks:
        sys.stdout.write("\n")
        sys.stdout.flush()

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    output = (stdout + stderr).strip()
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
