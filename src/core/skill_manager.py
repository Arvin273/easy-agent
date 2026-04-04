from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable


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
        self.workdir = (workdir or Path.cwd()).resolve()
        self.home = (home or Path.home()).resolve()
        self._skills_cache: list[SkillInfo] | None = None
        self._cache_stamp: tuple[str, ...] | None = None

    def _candidate_roots(self) -> list[Path]:
        home_root = (self.home / ".agents" / "skills").resolve()
        local_root = (self.workdir / ".agents" / "skills").resolve()
        roots: list[Path] = []
        for root in (home_root, local_root):
            if root not in roots:
                roots.append(root)
        return roots

    def _build_cache_stamp(self) -> tuple[str, ...]:
        stamp: list[str] = []
        for root in self._candidate_roots():
            if not root.exists() or not root.is_dir():
                stamp.append(f"{root}|missing")
                continue
            stamp.append(f"{root}|dir")
            for skill_dir in sorted(item for item in root.iterdir() if item.is_dir()):
                skill_file = skill_dir / SKILL_FILE_NAME
                if not skill_file.exists() or not skill_file.is_file():
                    continue
                stat = skill_file.stat()
                stamp.append(
                    f"{skill_file}|{stat.st_mtime_ns}|{stat.st_size}"
                )
        return tuple(stamp)

    @staticmethod
    def _parse_skill_metadata(skill_file: Path, directory_name: str) -> tuple[str, str]:
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception:
            return directory_name, ""

        lines = content.splitlines()
        name = ""
        description = ""

        # YAML front matter
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

        # name:/description: 行
        if not name:
            match = re.search(r"(?im)^\s*name\s*[:：]\s*(.+?)\s*$", content)
            if match:
                name = match.group(1).strip()
        if not description:
            match = re.search(r"(?im)^\s*description\s*[:：]\s*(.+?)\s*$", content)
            if match:
                description = match.group(1).strip()

        # 标题/首行兜底
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

    def discover_skills(self, force_refresh: bool = False) -> list[SkillInfo]:
        new_stamp = self._build_cache_stamp()
        if (
            not force_refresh
            and self._skills_cache is not None
            and self._cache_stamp == new_stamp
        ):
            return list(self._skills_cache)

        skills_by_key: dict[str, SkillInfo] = {}

        # home 先加载，cwd 后加载；同名时 cwd 覆盖 home
        for root in self._candidate_roots():
            if not root.exists() or not root.is_dir():
                continue
            for skill_dir in sorted(item for item in root.iterdir() if item.is_dir()):
                skill_file = skill_dir / SKILL_FILE_NAME
                if not skill_file.exists() or not skill_file.is_file():
                    continue
                name, description = self._parse_skill_metadata(skill_file, skill_dir.name)
                key = name.strip().lower() or skill_dir.name.strip().lower()
                skills_by_key[key] = (
                    SkillInfo(
                        name=name,
                        description=description,
                        directory_name=skill_dir.name,
                        directory=skill_dir,
                        skill_file=skill_file,
                    )
                )
        result = list(skills_by_key.values())
        self._skills_cache = result
        self._cache_stamp = new_stamp
        return list(result)

    def build_system_section(self) -> str:
        skills = self.discover_skills()
        if not skills:
            return ""

        lines = [
            "[Skills]",
            "你可以使用以下 skills（来源：当前工作目录和家目录的 .agents/skills）：",
        ]
        for skill in skills:
            desc = skill.description if skill.description else "(no description)"
            lines.append(f"- name: {skill.name}; description: {desc}")
        lines.append(
            "当用户请求明显匹配某个 skill 时，优先调用 read_skill 先读取该 skill 的 SKILL.md 再执行。"
        )
        return "\n".join(lines)

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "read_skill",
                "description": "读取指定 skill 的 SKILL.md 内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "skill 名称（目录名），例如 docker 或 rag-cli",
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return {"read_skill": self.run_read_skill}

    def refresh(self) -> bool:
        old_stamp = self._cache_stamp
        self.discover_skills(force_refresh=True)
        return old_stamp != self._cache_stamp

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
                            "skill_directory_name": skill.directory_name,
                            "skill_root": str(skill.directory),
                            "skill_file": str(skill.skill_file),
                        },
                        "content": content,
                    }
                    output = json.dumps(payload, ensure_ascii=False)
                    preview_lines = content.splitlines()
                    max_preview_lines = 10
                    if len(preview_lines) > max_preview_lines:
                        hidden = len(preview_lines) - max_preview_lines
                        preview_lines = preview_lines[:max_preview_lines] + [f"... ({hidden} more lines)"]
                    preview_text = "\n".join(preview_lines)
                    return {
                        "output": output,
                        "display_result": preview_text,
                    }
                except Exception as exc:
                    return f"Error: {exc}"
        return f"Error: Skill not found: {name.strip()}"
