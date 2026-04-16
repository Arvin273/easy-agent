from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gpt-5.4"
DEFAULT_EFFORT = "medium"
DEFAULT_TOKEN_THRESHOLD = 256000
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
    def home_mcp_config_path(self) -> Path:
        return self.app_dir / "mcp.json"

    @property
    def local_ea_dir(self) -> Path:
        return self.workdir / ".ea"

    @property
    def local_skills_dir(self) -> Path:
        return self.local_ea_dir / "skills"

    @property
    def local_mcp_config_path(self) -> Path:
        return self.local_ea_dir / "mcp.json"


PATHS = AppPaths(workdir=Path.cwd(), home=Path.home())
CONFIG_PATH = PATHS.config_path


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    base_url: str | None
    model: str
    effort: str
    token_threshold: int
    keep_recent_messages_count: int
    mcp_servers: list["MCPServerConfig"]


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args or []),
            "url": self.url,
            "env": dict(self.env or {}),
            "headers": dict(self.headers or {}),
        }


def _create_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default_content = _default_config_values()
    config_path.write_text(
        json.dumps(default_content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _create_default_mcp_config(config_path: Path) -> None:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"mcp_servers": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _persist_config_if_possible(config_path: Path, config: dict[str, Any]) -> None:
    try:
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _default_config_values() -> dict[str, str | int | list[Any]]:
    return {
        "api_key": "",
        "base_url": "",
        "model": DEFAULT_MODEL,
        "effort": DEFAULT_EFFORT,
        "token_threshold": DEFAULT_TOKEN_THRESHOLD,
        "keep_recent_messages_count": DEFAULT_KEEP_RECENT_MESSAGES_COUNT,
    }


def _normalize_config_payload(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(config)
    changed = False
    valid_keys = set(_default_config_values().keys())

    removable_keys = [key for key in normalized if key not in valid_keys]
    for key in removable_keys:
        normalized.pop(key, None)
        changed = True

    return normalized, changed


def _parse_string_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"配置项 {field_name} 必须是对象。")
    parsed: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"配置项 {field_name} 的键必须是非空字符串。")
        if not isinstance(item, str):
            raise ValueError(f"配置项 {field_name} 的值必须是字符串。")
        parsed[key] = item
    return parsed


def _parse_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"配置项 {field_name} 必须是数组。")
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"配置项 {field_name}[{index}] 必须是字符串。")
        parsed.append(item)
    return parsed


def _parse_mcp_servers(value: Any) -> list[MCPServerConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("配置项 mcp_servers 必须是数组。")

    servers: list[MCPServerConfig] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"配置项 mcp_servers[{index}] 必须是对象。")

        name = item.get("name")
        transport = item.get("transport")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"配置项 mcp_servers[{index}].name 必须是非空字符串。")
        clean_name = name.strip()
        if clean_name in names:
            raise ValueError(f"配置项 mcp_servers[{index}].name 重复: {clean_name}")
        names.add(clean_name)

        if not isinstance(transport, str) or transport.strip() not in {"stdio", "sse", "streamable_http"}:
            raise ValueError(
                f"配置项 mcp_servers[{index}].transport 必须是 stdio、sse 或 streamable_http。"
            )
        clean_transport = transport.strip()

        command = item.get("command")
        url = item.get("url")
        args = _parse_string_list(item.get("args"), f"mcp_servers[{index}].args")
        env = _parse_string_map(item.get("env"), f"mcp_servers[{index}].env")
        headers = _parse_string_map(item.get("headers"), f"mcp_servers[{index}].headers")

        if clean_transport == "stdio":
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"配置项 mcp_servers[{index}].command 在 stdio 模式下必须是非空字符串。")
            clean_command = command.strip()
            clean_url = None
        else:
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"配置项 mcp_servers[{index}].url 在 {clean_transport} 模式下必须是非空字符串。")
            clean_url = url.strip()
            clean_command = None

        servers.append(
            MCPServerConfig(
                name=clean_name,
                transport=clean_transport,
                command=clean_command,
                args=args,
                url=clean_url,
                env=env,
                headers=headers,
            )
        )
    return servers


def _load_single_mcp_config(path: Path) -> list[MCPServerConfig]:
    if not path.exists():
        return []
    if not path.is_file():
        raise FileNotFoundError(f"MCP 配置路径不是文件: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"MCP 配置文件解析失败: {path}: {exc}") from exc

    if isinstance(raw, list):
        return _parse_mcp_servers(raw)
    if isinstance(raw, dict):
        return _parse_mcp_servers(raw.get("mcp_servers"))
    raise ValueError(f"MCP 配置文件格式错误: {path}，根节点必须是对象或数组。")


def load_mcp_servers(paths: AppPaths | None = None) -> list[MCPServerConfig]:
    active_paths = paths or PATHS
    if not active_paths.home_mcp_config_path.exists():
        _create_default_mcp_config(active_paths.home_mcp_config_path)
    servers_by_name: dict[str, MCPServerConfig] = {}
    for path in (active_paths.home_mcp_config_path, active_paths.local_mcp_config_path):
        for server in _load_single_mcp_config(path):
            servers_by_name[server.name] = server
    return list(servers_by_name.values())


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

    config, normalized_changed = _normalize_config_payload(config)
    defaults = _default_config_values()
    has_missing_defaults = normalized_changed
    for key, default_value in defaults.items():
        if key not in config:
            config[key] = default_value
            has_missing_defaults = True
    if has_missing_defaults:
        _persist_config_if_possible(config_path, config)

    api_key = config.get("api_key")
    base_url = config.get("base_url")
    model = config.get("model", DEFAULT_MODEL)
    effort = config.get("effort", "medium")
    token_threshold = config.get("token_threshold", DEFAULT_TOKEN_THRESHOLD)
    keep_recent_messages_count = config.get("keep_recent_messages_count", DEFAULT_KEEP_RECENT_MESSAGES_COUNT)

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
    if not isinstance(keep_recent_messages_count, int) or keep_recent_messages_count < 0:
        raise ValueError("配置项 keep_recent_messages_count 必须是非负整数。")

    cleaned_base_url = base_url.strip() if isinstance(base_url, str) else None
    return AgentConfig(
        api_key=api_key.strip(),
        base_url=cleaned_base_url if cleaned_base_url else None,
        model=model.strip(),
        effort=effort.strip(),
        token_threshold=token_threshold,
        keep_recent_messages_count=keep_recent_messages_count,
        mcp_servers=load_mcp_servers(),
    )
