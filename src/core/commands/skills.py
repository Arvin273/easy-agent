from __future__ import annotations

from core.context.skill_manager import SkillManager
from core.terminal.cli_output import print_title_and_content

COMMAND = "/skills"
DESCRIPTION = "显示可用 skills"


def handle(skill_manager: SkillManager) -> bool:
    skills = skill_manager.discover_skills()
    if not skills:
        print_title_and_content("ai", "未发现可用 skills。", title="Available Skills")
        return False

    blocks: list[str] = []
    for index, skill in enumerate(skills, start=1):
        location = str(skill.directory.resolve())
        description = skill.description if skill.description else "(no description)"
        blocks.append(
            "\n".join(
                [
                    f"name: {skill.name}",
                    f"description: {description}",
                    f"location: {location}",
                ]
            )
        )
    print_title_and_content("ai", "\n\n".join(blocks), title="Available Skills")
    return False
