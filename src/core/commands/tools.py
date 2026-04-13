from __future__ import annotations

from typing import Any

from core.terminal.cli_output import Colors, print_title_and_content

COMMAND = "/tools"
DESCRIPTION = "显示当前可用 tools"


def handle(tool_registry: Any) -> bool:
    bundle = tool_registry.get_bundle()
    tools = bundle.tools
    if not tools:
        print_title_and_content(Colors.green, "当前没有可用 tools。\n\n", title="Available Tools")
        return False

    blocks: list[str] = []
    for index, tool in enumerate(tools, start=1):
        name = str(tool.get("name", f"tool-{index}"))
        description = str(tool.get("description", "") or "").strip() or "(no description)"
        blocks.append(
            "\n".join(
                [
                    f"name: {name}",
                    f"description: {description}",
                ]
            )
        )
    print_title_and_content(Colors.green, "\n\n".join(blocks) + "\n\n", title="Available Tools")
    return False
