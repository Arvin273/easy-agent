from typing import Any

from pathlib import Path

from core.tools.common import resolve_path


def _read_text_with_fallbacks(file_path: Path) -> tuple[str, str]:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return file_path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法按支持的编码读取文件: {file_path}")


def run_edit_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("file_path")
    old_text = arguments.get("old_string")
    new_text = arguments.get("new_string")
    replace_all = arguments.get("replace_all", False)

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 file_path 参数。")
    if not isinstance(old_text, str) or not old_text:
        raise ValueError("缺少有效的 old_string 参数。")
    if not isinstance(new_text, str):
        raise ValueError("缺少有效的 new_string 参数。")
    if old_text == new_text:
        raise ValueError("new_string 必须与 old_string 不同。")

    try:
        file_path = resolve_path(path_str)
        if not file_path.exists():
            return f"Error: 文件不存在: {path_str}"
        if not file_path.is_file():
            return f"Error: 目标不是普通文件: {path_str}"

        content, encoding = _read_text_with_fallbacks(file_path)
        occurrences = content.count(old_text)
        if occurrences == 0:
            return f"Error: old_string not found in {path_str}"
        if occurrences > 1 and not replace_all:
            return (
                f"Error: old_string appears {occurrences} times in {path_str}; "
                "请提供更精确的上下文或设置 replace_all=true"
            )

        updated_content = (
            content.replace(old_text, new_text)
            if replace_all
            else content.replace(old_text, new_text, 1)
        )
        file_path.write_text(updated_content, encoding=encoding)
        replaced_count = occurrences if replace_all else 1
        return f"Edited {path_str} ({replaced_count} replacement{'s' if replaced_count != 1 else ''})"
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "Edit"
TOOL_HANDLER = run_edit_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "此工具用于编辑文件：在文件中执行精确字符串替换。"
        "\n\n"
        "使用规则：\n"
        "- file_path 支持绝对路径和相对路径\n"
        "- old_string 必须是非空字符串，new_string 必须与 old_string 不同\n"
        "- 编辑从 read_file 输出中取得的文本时，必须保留行号前缀之后的原始缩进；不要把“行号 + 制表符”前缀包含进 old_string 或 new_string\n"
        "- 这个工具只修改已有文件，不会创建新文件；如果目标文件不存在会返回错误\n"
        "- 如果 old_string 在文件中不存在，编辑会失败\n"
        "- 如果 old_string 在文件中出现多次，而 replace_all 不是 true，编辑会失败；此时应提供更多上下文让 old_string 唯一，或者显式设置 replace_all=true\n"
        "- replace_all 适合在整个文件内批量替换同一段文本，例如重命名变量或统一替换字面量\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "工作区内文件的绝对路径或相对路径"},
            "old_string": {"type": "string", "description": "要被替换的原始文本"},
            "new_string": {"type": "string", "description": "替换后的新文本，必须与 old_string 不同"},
            "replace_all": {
                "type": "boolean",
                "description": "是否替换文件内 old_string 的全部出现位置，默认 false",
                "default": False,
            },
        },
        "required": ["file_path", "old_string", "new_string"],
        "additionalProperties": False,
    },
}
