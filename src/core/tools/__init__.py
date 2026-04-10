from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.tools.ask_user_question import TOOL_DEF as ASK_USER_QUESTION_TOOL_DEF
from core.tools.ask_user_question import TOOL_HANDLER as ASK_USER_QUESTION_TOOL_HANDLER
from core.tools.ask_user_question import TOOL_NAME as ASK_USER_QUESTION_TOOL_NAME
from core.tools.bash import TOOL_DEF as BASH_TOOL_DEF
from core.tools.bash import TOOL_HANDLER as BASH_TOOL_HANDLER
from core.tools.bash import TOOL_NAME as BASH_TOOL_NAME
from core.tools.common import WORKDIR
from core.tools.edit_file import TOOL_DEF as EDIT_FILE_TOOL_DEF
from core.tools.edit_file import TOOL_HANDLER as EDIT_FILE_TOOL_HANDLER
from core.tools.edit_file import TOOL_NAME as EDIT_FILE_TOOL_NAME
from core.tools.glob import TOOL_DEF as GLOB_TOOL_DEF
from core.tools.glob import TOOL_HANDLER as GLOB_TOOL_HANDLER
from core.tools.glob import TOOL_NAME as GLOB_TOOL_NAME
from core.tools.grep import TOOL_DEF as GREP_TOOL_DEF
from core.tools.grep import TOOL_HANDLER as GREP_TOOL_HANDLER
from core.tools.grep import TOOL_NAME as GREP_TOOL_NAME
from core.tools.read_file import TOOL_DEF as READ_FILE_TOOL_DEF
from core.tools.read_file import TOOL_HANDLER as READ_FILE_TOOL_HANDLER
from core.tools.read_file import TOOL_NAME as READ_FILE_TOOL_NAME
from core.tools.write_file import TOOL_DEF as WRITE_FILE_TOOL_DEF
from core.tools.write_file import TOOL_HANDLER as WRITE_FILE_TOOL_HANDLER
from core.tools.write_file import TOOL_NAME as WRITE_FILE_TOOL_NAME
from core.context.skill_manager import SkillManager
from core.config.config_manager import DEFAULT_MODEL


TOOL_HANDLERS = {
    BASH_TOOL_NAME: BASH_TOOL_HANDLER,
    READ_FILE_TOOL_NAME: READ_FILE_TOOL_HANDLER,
    WRITE_FILE_TOOL_NAME: WRITE_FILE_TOOL_HANDLER,
    EDIT_FILE_TOOL_NAME: EDIT_FILE_TOOL_HANDLER,
    GLOB_TOOL_NAME: GLOB_TOOL_HANDLER,
    GREP_TOOL_NAME: GREP_TOOL_HANDLER,
    ASK_USER_QUESTION_TOOL_NAME: ASK_USER_QUESTION_TOOL_HANDLER,
}

TOOLS = [
    BASH_TOOL_DEF,
    READ_FILE_TOOL_DEF,
    WRITE_FILE_TOOL_DEF,
    EDIT_FILE_TOOL_DEF,
    GLOB_TOOL_DEF,
    GREP_TOOL_DEF,
    ASK_USER_QUESTION_TOOL_DEF,
]


@dataclass(frozen=True)
class ToolBundle:
    tools: list[dict[str, Any]]
    handlers: dict[str, Callable[[dict[str, Any]], Any]]


class ToolRegistry:
    def __init__(self, skill_manager: SkillManager) -> None:
        self.skill_manager = skill_manager
        self._cached_bundle: ToolBundle | None = None

    def refresh(self) -> bool:
        changed = self.skill_manager.refresh()
        self._cached_bundle = self._build_bundle()
        return changed

    def get_bundle(self) -> ToolBundle:
        if self._cached_bundle is None:
            self._cached_bundle = self._build_bundle()
        return self._cached_bundle

    def _build_bundle(self) -> ToolBundle:
        tools = TOOLS + self.skill_manager.get_tools()
        handlers = {**TOOL_HANDLERS, **self.skill_manager.get_handlers()}
        return ToolBundle(tools=tools, handlers=handlers)

__all__ = ["DEFAULT_MODEL", "WORKDIR", "TOOL_HANDLERS", "TOOLS", "ToolBundle", "ToolRegistry"]
