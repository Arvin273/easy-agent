from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.builtin_tools import TOOL_HANDLERS, TOOLS
from core.skill_manager import SkillManager


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


