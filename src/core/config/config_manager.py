from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gpt-5.4"
DEFAULT_EFFORT = "medium"


@dataclass(frozen=True)
class AppPaths:
    workdir: Path
    home: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "workdir", self.workdir.resolve())
        object.__setattr__(self, "home", self.home.resolve())

    @property
    def app_dir(self) -> Path:
        return self.home / ".ea"

    @property
    def config_path(self) -> Path:
        return self.app_dir / "config.json"

    @property
    def home_skills_dir(self) -> Path:
        return self.app_dir / "skills"

    @property
    def local_ea_dir(self) -> Path:
        return self.workdir / ".ea"

    @property
    def local_skills_dir(self) -> Path:
        return self.local_ea_dir / "skills"


PATHS = AppPaths(workdir=Path.cwd(), home=Path.home())
CONFIG_PATH = PATHS.config_path


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    base_url: str | None
    model: str
    effort: str


def _create_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default_content = {
        "api_key": "",
        "base_url": "",
        "model": DEFAULT_MODEL,
        "effort": DEFAULT_EFFORT,
    }
    config_path.write_text(
        json.dumps(default_content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_agent_config(config_path: Path = CONFIG_PATH) -> AgentConfig:
    if not config_path.exists():
        _create_default_config(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"配置文件不是文件: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"配置文件解析失败: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError("配置文件格式错误：根节点必须是对象。")

    api_key = config.get("api_key")
    base_url = config.get("base_url")
    model = config.get("model", DEFAULT_MODEL)
    effort = config.get("effort", "medium")

    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError(
            f"配置缺少有效的 api_key。请编辑配置文件: {config_path}"
        )
    if base_url and not isinstance(base_url, str):
        raise ValueError("配置项 base_url 必须是字符串或 null。")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("配置项 model 必须是非空字符串。")
    if not isinstance(effort, str) or effort.strip() not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("配置项 effort 必须是 none、minimal、low、medium、high或xhigh")

    cleaned_base_url = base_url.strip() if isinstance(base_url, str) else None
    return AgentConfig(
        api_key=api_key.strip(),
        base_url=cleaned_base_url if cleaned_base_url else None,
        model=model.strip(),
        effort=effort.strip(),
    )
