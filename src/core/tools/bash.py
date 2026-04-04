import subprocess
import sys
from shutil import which
from typing import Any

from core.tools.common import WORKDIR


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
        result = subprocess.run(
            [bash_executable, "-lc", command],
            cwd=WORKDIR,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except RuntimeError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error: {exc}"

    stdout = decode_console_output(result.stdout)
    stderr = decode_console_output(result.stderr)
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
