from pathlib import Path

from core.config.config_manager import PATHS

WORKDIR = PATHS.workdir


def safe_path(path_str: str) -> Path:
    path = (WORKDIR / path_str).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path_str}")
    return path
