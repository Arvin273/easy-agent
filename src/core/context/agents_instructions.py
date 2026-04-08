from __future__ import annotations

from pathlib import Path

from core.config.config_manager import PATHS


def _read_agents_file(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        content = path.read_text(encoding="utf-8").strip()
        return content or None
    except Exception:
        return None


def load_agents_system_messages() -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    candidates = [
        ("应用数据目录", PATHS.app_dir / "AGENTS.md"),
        ("当前工作目录", PATHS.workdir / "AGENTS.md"),
    ]

    for source_name, path in candidates:
        content = _read_agents_file(path)
        if not content:
            continue
        messages.append(
            {
                "role": "system",
                "content": f"以下是来自{source_name}的 AGENTS.md 指令，请严格遵守：\n\n{content}",
            }
        )

    return messages
