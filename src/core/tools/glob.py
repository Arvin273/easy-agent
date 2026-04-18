from __future__ import annotations

from typing import Any

from core.tools.common import WORKDIR, resolve_path

MAX_GLOB_MATCHES = 200
MAX_GLOB_OUTPUT_CHARS = 12000


def _format_matches(matches: list[str]) -> str:
    if not matches:
        return "(no matches)"

    limited_matches = matches[:MAX_GLOB_MATCHES]
    output_lines: list[str] = []
    current_chars = 0
    truncated_by_chars = False

    for match in limited_matches:
        addition = len(match) if not output_lines else len(match) + 1
        if current_chars + addition > MAX_GLOB_OUTPUT_CHARS:
            truncated_by_chars = True
            break
        output_lines.append(match)
        current_chars += addition

    if not output_lines:
        first = limited_matches[0]
        if len(first) > MAX_GLOB_OUTPUT_CHARS:
            clipped = first[:MAX_GLOB_OUTPUT_CHARS]
            return f"{clipped}\n... [glob output truncated]"
        output_lines.append(first)

    truncated = len(matches) > len(output_lines) or truncated_by_chars
    output = "\n".join(output_lines)
    if truncated:
        hidden = len(matches) - len(output_lines)
        return f"{output}\n... [glob output truncated, {hidden} more matches]"
    return output


def run_glob(arguments: dict[str, Any]) -> str:
    pattern = arguments.get("pattern")
    path_value = arguments.get("path")

    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("缺少有效的 pattern 参数。")
    if path_value is not None and (not isinstance(path_value, str) or not path_value.strip()):
        raise ValueError("path 参数必须是有效目录路径，或直接省略。")

    try:
        base_dir = WORKDIR if path_value is None else resolve_path(path_value)
        if not base_dir.exists():
            return f"Error: 目录不存在: {base_dir}"
        if not base_dir.is_dir():
            return f"Error: 目标不是目录: {base_dir}"

        matches = [match for match in base_dir.glob(pattern) if match.is_file()]
        matches.sort(key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)

        if not matches:
            return "(no matches)"
        return _format_matches([str(match) for match in matches])
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "Glob"
TOOL_HANDLER = run_glob
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "- 快速文件模式匹配工具，适用于任意规模的代码库\n"
        "- 支持像 \"**/*.js\" 或 \"src/**/*.ts\" 这样的 glob 模式\n"
        "- 返回按修改时间排序的匹配文件路径\n"
        "- 当你需要按名称模式查找文件时，使用这个工具\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "要用于匹配文件的 glob 模式",
            },
            "path": {
                "type": "string",
                "description": "要搜索的目录。如果未指定，将使用当前工作目录。重要：使用默认目录时省略这个字段。不要填写“undefined”或“null” ，直接省略即可。若提供，必须是有效的目录路径。",
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
}
