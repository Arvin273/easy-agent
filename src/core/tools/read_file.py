from typing import Any

from core.tools.common import safe_path


def run_read_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    start_line = arguments.get("start_line")
    limit = arguments.get("limit")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if start_line is not None and not isinstance(start_line, int):
        raise ValueError("start_line 参数必须是整数。")
    if isinstance(start_line, int) and start_line < 1:
        raise ValueError("start_line 参数不能小于 1。")
    if limit is not None and not isinstance(limit, int):
        raise ValueError("limit 参数必须是整数。")
    if isinstance(limit, int) and limit < 0:
        raise ValueError("limit 参数不能小于 0。")

    try:
        file_path = safe_path(path_str)
        effective_start_line = start_line or 1
        effective_limit = limit if limit is not None else 200

        if effective_limit == 0:
            return "(no output)"

        rendered_lines: list[str] = []
        total_lines = 0
        encodings = ("utf-8", "gbk", "cp936")

        for encoding in encodings:
            try:
                with file_path.open("r", encoding=encoding) as file_obj:
                    for total_lines, line in enumerate(file_obj, start=1):
                        if total_lines < effective_start_line:
                            continue
                        if len(rendered_lines) >= effective_limit:
                            continue
                        rendered_lines.append(
                            f"{total_lines} | {line.rstrip(chr(10)).rstrip(chr(13))}"
                        )
                break
            except UnicodeDecodeError:
                rendered_lines = []
                total_lines = 0
                continue
        else:
            return f"Error: 无法按支持的编码读取文件: {path_str}"

        if effective_start_line > total_lines and total_lines > 0:
            return f"Error: start_line {effective_start_line} 超出文件总行数 {total_lines}"
        if total_lines == 0:
            return "(empty file)"

        end_line = effective_start_line + len(rendered_lines) - 1
        remaining = max(total_lines - end_line, 0)
        if remaining > 0:
            rendered_lines.append(f"... (remaining {remaining} lines)")

        return "\n".join(rendered_lines)
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "read_file"
TOOL_HANDLER = run_read_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "读取工作区内文件内容，可选返回前若干行。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "工作区内的相对文件路径"},
            "start_line": {
                "type": ["integer", "null"],
                "description": "起始行号，从 1 开始；null 表示从第一行开始",
            },
            "limit": {
                "type": ["integer", "null"],
                "description": "最多返回的行数；null 表示使用默认值200",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}
