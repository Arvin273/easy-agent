from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable

from core.config.config_manager import AppPaths, PATHS


SKILL_FILE_NAME = "SKILL.md"


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    directory_name: str
    directory: Path
    skill_file: Path


class SkillManager:
    def __init__(self, workdir: Path | None = None, home: Path | None = None) -> None:
        self.paths = AppPaths(
            workdir=workdir or PATHS.workdir,
            home=home or PATHS.home,
        )
        self.workdir = self.paths.workdir
        self.home = self.paths.home
        self._skills_cache: list[SkillInfo] | None = None

    def _candidate_roots(self) -> list[Path]:
        roots: list[Path] = []
        for root in (self.paths.home_skills_dir, self.paths.local_skills_dir):
            if root not in roots:
                roots.append(root)
        return roots

    @staticmethod
    def _parse_skill_metadata(skill_file: Path, directory_name: str) -> tuple[str, str]:
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception:
            return directory_name, ""

        lines = content.splitlines()
        name = ""
        description = ""

        if len(lines) >= 3 and lines[0].strip() == "---":
            for idx in range(1, len(lines)):
                if lines[idx].strip() == "---":
                    front_matter = lines[1:idx]
                    for raw in front_matter:
                        key, sep, value = raw.partition(":")
                        if not sep:
                            continue
                        k = key.strip().lower()
                        v = value.strip()
                        if k == "name" and v:
                            name = v
                        elif k == "description" and v:
                            description = v
                    break

        if not name:
            match = re.search(r"(?im)^\s*name\s*[:：]\s*(.+?)\s*$", content)
            if match:
                name = match.group(1).strip()
        if not description:
            match = re.search(r"(?im)^\s*description\s*[:：]\s*(.+?)\s*$", content)
            if match:
                description = match.group(1).strip()

        if not name:
            for line in lines:
                text = line.strip()
                if not text:
                    continue
                if text.startswith("#"):
                    heading = text.lstrip("#").strip()
                    if heading:
                        name = heading
                        break
                else:
                    name = text
                    break
        if not description:
            for line in lines:
                text = line.strip()
                if not text:
                    continue
                if text.startswith("#"):
                    continue
                if name and text == name:
                    continue
                description = text
                break

        return (name or directory_name)[:120], description[:240]

    def discover_skills(self) -> list[SkillInfo]:
        if self._skills_cache is not None:
            return list(self._skills_cache)

        skills_by_key: dict[str, SkillInfo] = {}

        for root in self._candidate_roots():
            if not root.exists() or not root.is_dir():
                continue
            for skill_dir in sorted(item for item in root.iterdir() if item.is_dir()):
                skill_file = skill_dir / SKILL_FILE_NAME
                if not skill_file.exists() or not skill_file.is_file():
                    continue
                name, description = self._parse_skill_metadata(skill_file, skill_dir.name)
                key = name.strip().lower() or skill_dir.name.strip().lower()
                skills_by_key[key] = SkillInfo(
                    name=name,
                    description=description,
                    directory_name=skill_dir.name,
                    directory=skill_dir,
                    skill_file=skill_file,
                )
        result = list(skills_by_key.values())
        self._skills_cache = result
        return list(result)

    def build_developer_section(self) -> str:
        skills = self.discover_skills()
        if not skills:
            return ""

        lines = [
            "你可以使用 Skill tool 加载以下skills：",
        ]
        for skill in skills:
            desc = skill.description if skill.description else "(no description)"
            lines.append(f"- name: {skill.name}; description: {desc}")
        return "\n".join(lines)

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "Skill",
                "description": (
                    "用于读取某个Skill的SKILL.md的内容"
                    "\n\n"
                    "重要规则: \n"
                    "当用户要求你执行任务时，检查是否有可用的技能与之匹配。技能提供了专用能力和领域知识。\n"
                    "当用户提到“$某个Skill名称”（例如 $commit、$review-pr）时，他们指的就是技能。使用此工具来读取对应的技能。\n"
                    "可用技能列表会在对话的系统提示词中给出\n"
                    "当某个技能与用户请求匹配时，这是强制性要求：必须先调用对应的 Skill 工具，再对任务生成其他任何回复\n"
                    "永远不要只提及某个技能，却不实际调用此工具\n"
                    "不要调用已经加载过的技能\n"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "skill 名称",
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return {"Skill": self.run_read_skill}

    def run_read_skill(self, arguments: dict[str, Any]) -> dict[str, str] | str:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("缺少有效的 name 参数。")

        target = name.strip().lower()
        for skill in self.discover_skills():
            if skill.name.strip().lower() == target or skill.directory_name.strip().lower() == target:
                try:
                    content = skill.skill_file.read_text(encoding="utf-8")
                    payload = {
                        "meta": {
                            "skill_name": skill.name,
                            "skill_root": str(skill.directory),
                            "skill_file": str(skill.skill_file),
                        },
                        "content": content,
                    }
                    output = json.dumps(payload, ensure_ascii=False)
                    return {"output": output}
                except Exception as exc:
                    return f"Error: {exc}"
        return f"Error: Skill not found: {name.strip()}"
