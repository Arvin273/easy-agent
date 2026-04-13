from __future__ import annotations

from core.config.config_manager import CONFIG_PATH, PATHS, load_agent_config
from core.terminal.cli_output import Colors, print_text, print_title_and_content

COMMAND = "/config"
DESCRIPTION = "查看当前配置"


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return "(missing)"
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def handle() -> bool:
    try:
        config = load_agent_config()
    except Exception as exc:
        print_text(Colors.error, f"读取配置失败: {exc}\n\n")
        return False

    lines = [
        f"config_path: {CONFIG_PATH}",
        f"workdir: {PATHS.workdir}",
        f"model: {config.model}",
        f"effort: {config.effort}",
        f"base_url: {config.base_url or '(default)'}",
        f"api_key: {_mask_api_key(config.api_key)}",
        f"token_threshold: {config.token_threshold}",
        f"keep_recent_tool_outputs: {config.keep_recent_tool_outputs}",
        f"min_compact_output_length: {config.min_compact_output_length}",
        f"keep_recent_messages_count: {config.keep_recent_messages_count}",
        f"mcp_servers: {len(config.mcp_servers)} configured",
    ]
    print_title_and_content(Colors.green, "\n".join(lines) + "\n\n", title="Config")
    return False
