from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Callable

from openai import OpenAI

from core.commands import clear as clear_command
from core.commands import copy as copy_command
from core.commands import compact as compact_command
from core.commands import config as config_command
from core.commands import exit as exit_command
from core.commands import help as help_command
from core.commands import jobs as jobs_command
from core.commands import model as model_command
from core.commands import skills as skills_command
from core.commands import tools as tools_command
from core.commands import tokens as tokens_command
from core.context.skill_manager import SkillManager
from core.terminal.cli_output import Colors, print_text


@dataclass(frozen=True)
class SlashCommandContext:
    skill_manager: SkillManager
    tool_registry: Any
    client: OpenAI | None
    model: str | None
    history: list[dict[str, Any] | Any] | None
    keep_recent_messages_count: int
    token_threshold: int
    args: list[str]


SLASH_COMMANDS = {
    config_command.COMMAND: config_command.DESCRIPTION,
    clear_command.COMMAND: clear_command.DESCRIPTION,
    copy_command.COMMAND: copy_command.DESCRIPTION,
    help_command.COMMAND: help_command.DESCRIPTION,
    jobs_command.COMMAND: jobs_command.DESCRIPTION,
    skills_command.COMMAND: skills_command.DESCRIPTION,
    tools_command.COMMAND: tools_command.DESCRIPTION,
    model_command.COMMAND: model_command.DESCRIPTION,
    compact_command.COMMAND: compact_command.DESCRIPTION,
    tokens_command.COMMAND: tokens_command.DESCRIPTION,
    exit_command.COMMAND: exit_command.DESCRIPTION,
}


def _handle_help(_: SlashCommandContext) -> bool:
    return help_command.handle(SLASH_COMMANDS)


def _handle_config(_: SlashCommandContext) -> bool:
    return config_command.handle()


def _handle_clear(context: SlashCommandContext) -> bool:
    return clear_command.handle(context.history)


def _handle_copy(context: SlashCommandContext) -> bool:
    return copy_command.handle(context.history)


def _handle_jobs(context: SlashCommandContext) -> bool:
    return jobs_command.handle(context.args)


def _handle_skills(context: SlashCommandContext) -> bool:
    return skills_command.handle(context.skill_manager)


def _handle_tools(context: SlashCommandContext) -> bool:
    return tools_command.handle(context.tool_registry)


def _handle_model(_: SlashCommandContext) -> bool:
    return model_command.handle()


def _handle_compact(context: SlashCommandContext) -> bool:
    return compact_command.handle(
        client=context.client,
        model=context.model,
        history=context.history,
        keep_recent_messages_count=context.keep_recent_messages_count,
    )


def _handle_tokens(context: SlashCommandContext) -> bool:
    return tokens_command.handle(context.history, context.token_threshold)


def _handle_exit(_: SlashCommandContext) -> bool:
    return exit_command.handle()


COMMAND_HANDLERS: dict[str, Callable[[SlashCommandContext], bool]] = {
    config_command.COMMAND: _handle_config,
    clear_command.COMMAND: _handle_clear,
    copy_command.COMMAND: _handle_copy,
    help_command.COMMAND: _handle_help,
    jobs_command.COMMAND: _handle_jobs,
    skills_command.COMMAND: _handle_skills,
    tools_command.COMMAND: _handle_tools,
    model_command.COMMAND: _handle_model,
    compact_command.COMMAND: _handle_compact,
    tokens_command.COMMAND: _handle_tokens,
    exit_command.COMMAND: _handle_exit,
}


def get_slash_command_descriptions() -> dict[str, str]:
    return dict(SLASH_COMMANDS)


def handle_slash_command(
    query: str,
    skill_manager: SkillManager,
    tool_registry: Any,
    client: OpenAI | None = None,
    model: str | None = None,
    history: list[dict[str, Any] | Any] | None = None,
    keep_recent_messages_count: int = 0,
    token_threshold: int = 0,
) -> bool:
    parts = query.strip().split()
    if not parts:
        return False
    command = parts[0].lower()
    handler = COMMAND_HANDLERS.get(command)
    if handler is not None:
        context = SlashCommandContext(
            skill_manager=skill_manager,
            tool_registry=tool_registry,
            client=client,
            model=model,
            history=history,
            keep_recent_messages_count=keep_recent_messages_count,
            token_threshold=token_threshold,
            args=parts[1:],
        )
        return handler(context)
    print_text(Colors.error, f"Unknown slash command: {query}。输入 /help 查看可用命令。\n\n")
    return False
