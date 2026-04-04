from typing import Any

from core.tools.common import safe_path


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


TOOL_NAME = "write_file"
TOOL_HANDLER = run_write_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
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
}
