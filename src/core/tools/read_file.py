from typing import Any

from core.tools.common import parse_optional_int, resolve_path


def run_read_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    start_line = parse_optional_int(arguments.get("start_line"), "start_line")
    limit = parse_optional_int(arguments.get("limit"), "limit")
    if start_line is not None and start_line < 1:
        raise ValueError("start_line 参数不能小于 1。")
    if limit is not None and limit < 0:
        raise ValueError("limit 参数不能小于 0。")

    try:
        file_path = resolve_path(path_str)
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
                        rendered_lines.append(f"{total_lines}\t{line.rstrip(chr(10)).rstrip(chr(13))}")
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


TOOL_NAME = "Read"
TOOL_HANDLER = run_read_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "读取本地文件系统中的文件内容。"
        "你可以通过这个工具直接读取任意文件；如果传入的文件不存在，工具会返回错误。"
        "\n\n"
        "使用规则：\n"
        "- 可以通过 start_line 和 limit 指定读取范围；文件较长时建议这样做\n"
        "- 返回结果格式为“行号 + 制表符 + 内容”\n"
        "- 这个工具只能读取文件，不能读取目录；要查看目录请使用 shell 工具\n"
        "- 如果读取到空文件，会返回明确提示\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件绝对路径或相对路径"},
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
