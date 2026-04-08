from __future__ import annotations

from typing import Callable

from core.terminal.cli_output import print_box
from core.commands import exit as exit_command
from core.commands import help as help_command
from core.commands import model as model_command
from core.commands import skills as skills_command
from core.context.skill_manager import SkillManager

SLASH_COMMANDS = {
    help_command.COMMAND: help_command.DESCRIPTION,
    skills_command.COMMAND: skills_command.DESCRIPTION,
    model_command.COMMAND: model_command.DESCRIPTION,
    exit_command.COMMAND: exit_command.DESCRIPTION,
}


def _handle_help(_: SkillManager) -> bool:
    return help_command.handle(SLASH_COMMANDS)


def _handle_skills(skill_manager: SkillManager) -> bool:
    return skills_command.handle(skill_manager)


def _handle_model(_: SkillManager) -> bool:
    return model_command.handle()


def _handle_exit(_: SkillManager) -> bool:
    return exit_command.handle()


COMMAND_HANDLERS: dict[str, Callable[[SkillManager], bool]] = {
    help_command.COMMAND: _handle_help,
    skills_command.COMMAND: _handle_skills,
    model_command.COMMAND: _handle_model,
    exit_command.COMMAND: _handle_exit,
}


def handle_slash_command(query: str, skill_manager: SkillManager) -> bool:
    command = query.lower()
    handler = COMMAND_HANDLERS.get(command)
    if handler is not None:
        return handler(skill_manager)
    print_box("error", f"Unknown slash command: {query}。输入 /help 查看可用命令。", title="Error")
    return False
