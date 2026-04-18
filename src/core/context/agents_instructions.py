from __future__ import annotations

from pathlib import Path

from core.config.config_manager import PATHS


def _read_agents_file(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        content = path.read_text(encoding="utf-8").strip()
        return content
    except Exception:
        return None


def load_agents_system_messages() -> list[dict[str, str]]:
    sections: list[str] = []
    candidates = [
        ("用户级指令", PATHS.app_dir / "AGENTS.md"),
        ("项目级指令", PATHS.workdir / "AGENTS.md"),
    ]

    for label, path in candidates:
        content = _read_agents_file(path)
        if content is None:
            continue
        if content:
            sections.append(f"{label}：\n{content}")
        else:
            sections.append(f"{label}：空")

    if not sections:
        return []

    merged = (
        "你在回答用户问题时，必须严格遵守这些指令：\n"
        f"{'\n\n'.join(sections)}\n\n"
        "重要：这些指令可能会覆盖默认行为，你必须完全遵守。\n"
        "重要：这些指令不一定和当前任务相关。只有在它们和当前任务高度相关时，才在回答中体现。\n"
        "重要：如果用户级指令和项目级指令存在冲突，请以项目级指令为准。\n"
    )
    return [{"role": "system", "content": merged}]
