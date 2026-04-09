from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gpt-5.4"
DEFAULT_EFFORT = "medium"
DEFAULT_TOKEN_THRESHOLD = 100000
DEFAULT_KEEP_RECENT_TOOL_OUTPUTS = 10
DEFAULT_MIN_COMPACT_OUTPUT_LENGTH = 100
DEFAULT_KEEP_RECENT_MESSAGES_COUNT = 10


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
    token_threshold: int
    keep_recent_tool_outputs: int
    min_compact_output_length: int
    keep_recent_messages_count: int


def _create_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default_content = {
        "api_key": "",
        "base_url": "",
        "model": DEFAULT_MODEL,
        "effort": DEFAULT_EFFORT,
        "token_threshold": DEFAULT_TOKEN_THRESHOLD,
        "keep_recent_tool_outputs": DEFAULT_KEEP_RECENT_TOOL_OUTPUTS,
        "min_compact_output_length": DEFAULT_MIN_COMPACT_OUTPUT_LENGTH,
        "keep_recent_messages_count": DEFAULT_KEEP_RECENT_MESSAGES_COUNT,
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
    token_threshold = config.get("token_threshold", DEFAULT_TOKEN_THRESHOLD)
    keep_recent_tool_outputs = config.get("keep_recent_tool_outputs", DEFAULT_KEEP_RECENT_TOOL_OUTPUTS)
    min_compact_output_length = config.get("min_compact_output_length", DEFAULT_MIN_COMPACT_OUTPUT_LENGTH)
    keep_recent_messages_count = config.get("keep_recent_messages_count")
    if keep_recent_messages_count is None:
        keep_recent_messages_count = config.get("keep_recent_messages_days", DEFAULT_KEEP_RECENT_MESSAGES_COUNT)

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
    if not isinstance(token_threshold, int) or token_threshold <= 0:
        raise ValueError("配置项 token_threshold 必须是正整数。")
    if not isinstance(keep_recent_tool_outputs, int) or keep_recent_tool_outputs < 0:
        raise ValueError("配置项 keep_recent_tool_outputs 必须是非负整数。")
    if not isinstance(min_compact_output_length, int) or min_compact_output_length < 0:
        raise ValueError("配置项 min_compact_output_length 必须是非负整数。")
    if not isinstance(keep_recent_messages_count, int) or keep_recent_messages_count < 0:
        raise ValueError("配置项 keep_recent_messages_count 必须是非负整数。")

    if "keep_recent_messages_count" not in config:
        config["keep_recent_messages_count"] = keep_recent_messages_count
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    cleaned_base_url = base_url.strip() if isinstance(base_url, str) else None
    return AgentConfig(
        api_key=api_key.strip(),
        base_url=cleaned_base_url if cleaned_base_url else None,
        model=model.strip(),
        effort=effort.strip(),
        token_threshold=token_threshold,
        keep_recent_tool_outputs=keep_recent_tool_outputs,
        min_compact_output_length=min_compact_output_length,
        keep_recent_messages_count=keep_recent_messages_count,
    )
