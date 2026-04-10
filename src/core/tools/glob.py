from __future__ import annotations

from pathlib import Path
from typing import Any

from core.tools.common import WORKDIR, resolve_path


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
        return "\n".join(str(match) for match in matches)
    except Exception as exc:
        return f"Error: {exc}"


TOOL_NAME = "Glob"
TOOL_HANDLER = run_glob
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    # TODO：必须实现Agent工具
    "description": (
        "- 快速文件模式匹配工具，适用于任意规模的代码库\n"
        "- 支持像 \"**/*.js\" 或 \"src/**/*.ts\" 这样的 glob 模式\n"
        "- 返回按修改时间排序的匹配文件路径\n"
        "- 当你需要按名称模式查找文件时，使用这个工具\n"
        "- 当你在做可能需要多轮 glob 和 grep 的开放式搜索时，使用 Agent 工具替代\n"
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
