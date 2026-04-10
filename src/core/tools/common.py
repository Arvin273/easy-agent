from pathlib import Path

from core.config.config_manager import PATHS

WORKDIR = PATHS.workdir


def resolve_path(path_str: str) -> Path:
    raw_path = Path(path_str)
    return raw_path.resolve() if raw_path.is_absolute() else (WORKDIR / raw_path).resolve()
