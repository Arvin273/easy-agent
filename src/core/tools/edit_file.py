from typing import Any

from core.tools.common import safe_path


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


TOOL_NAME = "edit_file"
TOOL_HANDLER = run_edit_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
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
}
