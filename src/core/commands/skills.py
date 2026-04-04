from __future__ import annotations

from core.cli_output import print_box
from core.skill_manager import SkillManager

COMMAND = "/skills"
DESCRIPTION = "显示可用 skills"


def handle(skill_manager: SkillManager) -> bool:
    skills = skill_manager.discover_skills()
    if not skills:
        print_box("ai", "未发现可用 skills。", title="Skills")
        return False

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
    return False
