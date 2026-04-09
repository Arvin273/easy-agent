from __future__ import annotations

from core.terminal.cli_output import print_title_and_content

COMMAND = "/help"
DESCRIPTION = "显示命令帮助"


def handle(command_descriptions: dict[str, str]) -> bool:
    command_list = sorted(command_descriptions.keys())
    lines = ["可用命令:"]
    for command in command_list:
        lines.append(f"- {command} {command_descriptions.get(command, '')}".rstrip())
    print_title_and_content("ai", "\n".join(lines) + "\n\n", title="Slash Commands")
    return False
