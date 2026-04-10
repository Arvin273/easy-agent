from pathlib import Path
from typing import Any

from core.config.config_manager import PATHS

WORKDIR = PATHS.workdir


def resolve_path(path_str: str) -> Path:
    raw_path = Path(path_str)
    return raw_path.resolve() if raw_path.is_absolute() else (WORKDIR / raw_path).resolve()


def parse_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 参数必须是整数。")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} 参数必须是整数。")
        try:
            return int(stripped)
        except ValueError as exc:
            raise ValueError(f"{field_name} 参数必须是整数。") from exc
    raise ValueError(f"{field_name} 参数必须是整数。")
