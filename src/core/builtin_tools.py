import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Any


WORKDIR = Path.cwd()


def safe_path(path_str: str) -> Path:
    path = (WORKDIR / path_str).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path_str}")
    return path


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


def run_read_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    limit = arguments.get("limit")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if limit is not None and not isinstance(limit, int):
        raise ValueError("limit 参数必须是整数。")
    if isinstance(limit, int) and limit < 0:
        raise ValueError("limit 参数不能小于 0。")

    try:
        lines = safe_path(path_str).read_text(encoding="utf-8").splitlines()
        if limit is not None and limit < len(lines):
            remaining = len(lines) - limit
            lines = lines[:limit] + [f"... ({remaining} more)"]
        return "\n".join(lines)[:50000]
    except Exception as exc:
        return f"Error: {exc}"


def run_write_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    content = arguments.get("content")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if not isinstance(content, str):
        raise ValueError("缺少有效的 content 参数。")

    try:
        file_path = safe_path(path_str)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes"
    except Exception as exc:
        return f"Error: {exc}"


def run_edit_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if not isinstance(old_text, str):
        raise ValueError("缺少有效的 old_text 参数。")
    if not isinstance(new_text, str):
        raise ValueError("缺少有效的 new_text 参数。")

    try:
        file_path = safe_path(path_str)
        content = file_path.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path_str}"
        file_path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path_str}"
    except Exception as exc:
        return f"Error: {exc}"


TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read_file,
    "write_file": run_write_file,
    "edit_file": run_edit_file,
}


TOOLS = [
    {
        "type": "function",
        "name": "bash",
        "description": "在工作区内执行一个 shell 命令，并返回标准输出和标准错误输出。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "读取工作区内文件内容，可选返回前若干行。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内的相对文件路径"},
                "limit": {
                    "type": ["integer", "null"],
                    "description": "最多返回的行数，可选；null 表示不限制",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "向工作区内文件写入完整内容，不存在则创建。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内的相对文件路径"},
                "content": {"type": "string", "description": "要写入的完整文本内容"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "edit_file",
        "description": "在工作区内文件中执行一次精确文本替换。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内的相对文件路径"},
                "old_text": {"type": "string", "description": "要被替换的原始文本"},
                "new_text": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
    },
]
