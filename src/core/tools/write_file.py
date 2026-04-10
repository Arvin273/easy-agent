from typing import Any
from pathlib import Path
from uuid import uuid4

from core.tools.common import resolve_path


def _detect_text_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法按支持的编码读取文件: {file_path}")


def _atomic_write_text(file_path: Path, content: str, encoding: str) -> None:
    temp_path = file_path.with_name(f"{file_path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(content, encoding=encoding)
    temp_path.replace(file_path)


def run_write_file(arguments: dict[str, Any]) -> str:
    path_str = arguments.get("path")
    content = arguments.get("content")
    overwrite = arguments.get("overwrite", False)

    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("缺少有效的 path 参数。")
    if not isinstance(content, str):
        raise ValueError("缺少有效的 content 参数。")

    try:
        file_path = resolve_path(path_str)
        if file_path.exists() and file_path.is_dir():
            return f"Error: 目标是目录，不是文件: {path_str}"

        encoding = "utf-8"
        if file_path.exists():
            if not overwrite:
                return f"Error: 文件已存在，若要覆盖请设置 overwrite=true: {path_str}"
            if not file_path.is_file():
                return f"Error: 目标不是普通文件: {path_str}"
            encoding = _detect_text_encoding(file_path)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(file_path, content, encoding=encoding)
        byte_count = len(content.encode(encoding))
        return f"Wrote {byte_count} bytes to {path_str}"
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "Write"
TOOL_HANDLER = run_write_file
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "向本地文件系统写入文件内容。"
        "\n\n"
        "使用规则：\n"
        "- 如果目标路径已存在文件，只有在 overwrite=true 时才会覆盖原内容\n"
        "- 这个工具适合创建新文件，或对现有文件执行完整重写\n"
        "- 如果只是修改现有文件的一部分，优先使用 edit_file，而不是整文件重写\n"
        "- 如果目标文件的父目录不存在，工具会自动创建目录\n"
        "- 如果覆盖现有文本文件，工具会尽量保留原文件编码\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要写入的文件路径，支持绝对路径和相对路径"},
            "content": {"type": "string", "description": "要写入的完整文本内容"},
            "overwrite": {
                "type": "boolean",
                "description": "目标文件已存在时是否允许覆盖，默认 false",
                "default": False,
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}
