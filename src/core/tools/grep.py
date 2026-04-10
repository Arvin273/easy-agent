from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.tools.common import WORKDIR, parse_optional_int, resolve_path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _parse_optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} 参数必须是布尔值。")


def _decode_output(data: bytes) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _resolve_rg_executable() -> str | None:
    base_dir = PACKAGE_ROOT / "vendor" / "ripgrep"
    machine = platform.machine().lower()
    arch_map = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    if sys.platform.startswith("win"):
        candidate = base_dir / f"{arch}-win32" / "rg.exe"
    elif sys.platform == "darwin":
        candidate = base_dir / f"{arch}-darwin" / "rg"
    else:
        candidate = base_dir / f"{arch}-linux" / "rg"

    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _slice_output_lines(output: str, offset: int, head_limit: int) -> str:
    if not output.strip():
        return "(no matches)"
    lines = output.splitlines()
    sliced = lines[offset:]
    if head_limit != 0:
        sliced = sliced[:head_limit]
    if not sliced:
        return "(no matches)"
    return "\n".join(sliced)


def run_grep(arguments: dict[str, Any]) -> str:
    pattern = arguments.get("pattern")
    path_value = arguments.get("path")
    glob_value = arguments.get("glob")
    output_mode = arguments.get("output_mode", "files_with_matches")
    before_context = parse_optional_int(arguments.get("-B"), "-B")
    after_context = parse_optional_int(arguments.get("-A"), "-A")
    context_alias = parse_optional_int(arguments.get("-C"), "-C")
    context = parse_optional_int(arguments.get("context"), "context")
    show_line_numbers = arguments.get("-n", True)
    case_insensitive = arguments.get("-i")
    file_type = arguments.get("type")
    head_limit = parse_optional_int(arguments.get("head_limit"), "head_limit")
    offset = parse_optional_int(arguments.get("offset"), "offset")
    multiline = arguments.get("multiline", False)

    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("缺少有效的 pattern 参数。")
    if path_value is not None and (not isinstance(path_value, str) or not path_value.strip()):
        raise ValueError("path 参数必须是有效路径，或直接省略。")
    if glob_value is not None and (not isinstance(glob_value, str) or not glob_value.strip()):
        raise ValueError("glob 参数必须是非空字符串。")
    if output_mode not in {"content", "files_with_matches", "count"}:
        raise ValueError("output_mode 参数无效。")
    if before_context is not None and before_context < 0:
        raise ValueError("-B 参数不能小于 0。")
    if after_context is not None and after_context < 0:
        raise ValueError("-A 参数不能小于 0。")
    if context_alias is not None and context_alias < 0:
        raise ValueError("-C 参数不能小于 0。")
    if context is not None and context < 0:
        raise ValueError("context 参数不能小于 0。")
    if head_limit is not None and head_limit < 0:
        raise ValueError("head_limit 参数不能小于 0。")
    if offset is not None and offset < 0:
        raise ValueError("offset 参数不能小于 0。")
    if file_type is not None and (not isinstance(file_type, str) or not file_type.strip()):
        raise ValueError("type 参数必须是非空字符串。")

    show_line_numbers_value = _parse_optional_bool(show_line_numbers, "-n")
    case_insensitive_value = _parse_optional_bool(case_insensitive, "-i")
    multiline_value = _parse_optional_bool(multiline, "multiline")

    resolved_path = WORKDIR if path_value is None else resolve_path(path_value)
    if not resolved_path.exists():
        return f"Error: 路径不存在: {resolved_path}"

    rg_path = _resolve_rg_executable()
    if not rg_path:
        return "Error: 未找到内置 rg 可执行文件"

    command = [rg_path]
    command.append("--no-messages")
    if output_mode == "files_with_matches":
        command.append("-l")
    elif output_mode == "count":
        command.append("-c")
    else:
        if show_line_numbers_value is not False:
            command.append("-n")
        if context is not None:
            command.extend(["-C", str(context)])
        elif context_alias is not None:
            command.extend(["-C", str(context_alias)])
        if before_context is not None:
            command.extend(["-B", str(before_context)])
        if after_context is not None:
            command.extend(["-A", str(after_context)])

    if case_insensitive_value:
        command.append("-i")
    if file_type is not None:
        command.extend(["--type", file_type.strip()])
    if glob_value is not None:
        command.extend(["--glob", glob_value.strip()])
    if multiline_value:
        command.extend(["-U", "--multiline-dotall"])

    command.extend([pattern, str(resolved_path)])

    try:
        completed = subprocess.run(
            command,
            cwd=WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except Exception as exc:
        return f"Error: {exc}"

    if completed.returncode not in {0, 1}:
        error_output = _decode_output(completed.stderr).strip()
        if completed.returncode == 2 and not error_output:
            output = _decode_output(completed.stdout).strip()
            effective_offset = offset or 0
            effective_head_limit = 250 if head_limit is None else head_limit
            return _slice_output_lines(output, effective_offset, effective_head_limit)
        return f"Error: {error_output or f'rg exited with code {completed.returncode}'}"

    output = _decode_output(completed.stdout).strip()
    effective_offset = offset or 0
    effective_head_limit = 250 if head_limit is None else head_limit
    return _slice_output_lines(output, effective_offset, effective_head_limit)


TOOL_NAME = "Grep"
TOOL_HANDLER = run_grep
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "一个基于 ripgrep 的强大搜索工具\n\n"
        "  用法：\n"
        "  - 搜索任务一律使用 Grep。绝不要通过 Bash 命令调用 `grep` 或 `rg`。Grep 工具已经针对正确的权限和访问做了优化。\n"
        "  - 支持完整正则表达式语法（例如：\"log.*Error\"、\"function\\\\s+\\\\w+\"）\n"
        "  - 可通过 glob 参数（例如：\"*.js\"、\"**/*.tsx\"）或 type 参数（例如：\"js\"、\"py\"、\"rust\"）过滤文件\n"
        "  - 输出模式：\"content\" 显示匹配行，\"files_with_matches\" 仅显示文件路径（默认），\"count\" 显示匹配计数\n"
        "  - 需要多轮搜索的开放式查找请使用 Agent 工具\n"
        "  - 模式语法：使用 ripgrep（不是 grep）- 字面量花括号需要转义（例如在 Go 代码中搜索 `interface{}` 时，使用 `interface\\\\{\\\\}`）\n"
        "  - 多行匹配：默认模式只在单行内匹配。对于像 `struct \\\\{[\\\\s\\\\S]*?field` 这样的跨行模式，使用 `multiline: true`\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "description": "要在文件内容中搜索的正则表达式模式",
                "type": "string",
            },
            "path": {
                "description": "要搜索的文件或目录（rg PATH）。默认使用当前工作目录。",
                "type": "string",
            },
            "glob": {
                "description": "用于过滤文件的 glob 模式（例如 \"*.js\"、\"*.{ts,tsx}\"）- 映射到 rg --glob",
                "type": "string",
            },
            "output_mode": {
                "description": "输出模式：\"content\" 显示匹配行（支持 -A/-B/-C 上下文、-n 行号、head_limit），\"files_with_matches\" 显示文件路径（支持 head_limit），\"count\" 显示匹配计数（支持 head_limit）。默认是 \"files_with_matches\"。",
                "type": "string",
                "enum": [
                    "content",
                    "files_with_matches",
                    "count",
                ],
            },
            "-B": {
                "description": "显示每个匹配之前的行数（rg -B）。要求 output_mode: \"content\"，否则忽略。",
                "type": "number",
            },
            "-A": {
                "description": "显示每个匹配之后的行数（rg -A）。要求 output_mode: \"content\"，否则忽略。",
                "type": "number",
            },
            "-C": {
                "description": "context 的别名。",
                "type": "number",
            },
            "context": {
                "description": "显示每个匹配前后的行数（rg -C）。要求 output_mode: \"content\"，否则忽略。",
                "type": "number",
            },
            "-n": {
                "description": "在输出中显示行号（rg -n）。要求 output_mode: \"content\"，否则忽略。默认 true。",
                "type": "boolean",
            },
            "-i": {
                "description": "大小写不敏感搜索（rg -i）",
                "type": "boolean",
            },
            "type": {
                "description": "要搜索的文件类型（rg --type）。常见类型：js、py、rust、go、java 等。对标准文件类型来说，比 include 更高效。",
                "type": "string",
            },
            "head_limit": {
                "description": "将输出限制为前 N 行或前 N 条，等价于 \"| head -N\"。适用于所有输出模式：content（限制输出行）、files_with_matches（限制文件路径）、count（限制计数条目）。未指定时默认 250。传 0 表示不限制（谨慎使用，大结果集会浪费上下文）。",
                "type": "number",
            },
            "offset": {
                "description": "在应用 head_limit 之前跳过前 N 行或前 N 条，等价于 \"| tail -n +N | head -N\"。适用于所有输出模式。默认 0。",
                "type": "number",
            },
            "multiline": {
                "description": "启用多行模式，此时 . 可以匹配换行，模式也可以跨行匹配（rg -U --multiline-dotall）。默认：false。",
                "type": "boolean",
            },
        },
        "required": [
            "pattern",
        ],
        "additionalProperties": False,
    },
}
