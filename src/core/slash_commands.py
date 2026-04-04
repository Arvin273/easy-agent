from __future__ import annotations

from typing import Callable

from core.cli_output import print_box
from core.skill_manager import SkillManager


SLASH_COMMANDS = {
    "/exit": "退出应用",
    "/help": "显示命令帮助",
    "/skills": "显示可用 skills",
}


def print_slash_commands() -> None:
    command_list = sorted(SLASH_COMMANDS.keys())
    lines = ["可用命令:"]
    for command in command_list:
        lines.append(f"- {command} {SLASH_COMMANDS.get(command, '')}".rstrip())
    print_box("ai", "\n".join(lines), title="Slash Commands")


def print_available_skills(skill_manager: SkillManager) -> None:
    skills = skill_manager.discover_skills()
    if not skills:
        print_box("ai", "未发现可用 skills。", title="Skills")
        return

    workdir_root = (skill_manager.workdir / ".agents" / "skills").resolve()
    home_root = (skill_manager.home / ".agents" / "skills").resolve()
    blocks: list[str] = []
    for index, skill in enumerate(skills, start=1):
        location = "工作区"
        if skill.directory.resolve().is_relative_to(home_root):
            location = "家目录"
        if skill.directory.resolve().is_relative_to(workdir_root):
            location = "工作区"
        description = skill.description if skill.description else "(no description)"
        blocks.append(
            "\n".join(
                [
                    f"{index}.",
                    f"name: {skill.name}",
                    f"description: {description}",
                    f"location: {location}",
                ]
            )
        )
    print_box("ai", "\n\n".join(blocks), title="Skills")


def _handle_help(_: SkillManager) -> bool:
    print_slash_commands()
    return False


def _handle_skills(skill_manager: SkillManager) -> bool:
    print_available_skills(skill_manager)
    return False


def _handle_exit(_: SkillManager) -> bool:
    return True


COMMAND_HANDLERS: dict[str, Callable[[SkillManager], bool]] = {
    "/help": _handle_help,
    "/skills": _handle_skills,
    "/exit": _handle_exit,
}


def handle_slash_command(query: str, skill_manager: SkillManager) -> bool:
    command = query.lower()
    handler = COMMAND_HANDLERS.get(command)
    if handler is not None:
        return handler(skill_manager)
    print_box("error", f"Unknown slash command: {query}\n输入 /help 查看可用命令。", title="Error")
    return False

