from __future__ import annotations

import json
from pathlib import Path

from core.config.config_manager import CONFIG_PATH, DEFAULT_EFFORT, DEFAULT_MODEL
from core.terminal.cli_output import print_title_and_content, print_text
from core.terminal.prompt_ui import select_option

COMMAND = "/model"
DESCRIPTION = "切换模型与推理强度"

MODEL_OPTIONS = [
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5.3-codex",
    "gpt-5.1-codex-max",
]

EFFORT_OPTIONS = ["none", "minimal", "low", "medium", "high", "xhigh"]

def _select_from_options(options: list[str], default_index: int = 0) -> str:
    if not options:
        raise ValueError("options 不能为空。")
    if default_index < 0 or default_index >= len(options):
        default_index = 0

    option_pairs = [(option, option) for option in options]
    return select_option(
        options=option_pairs,
        default=options[default_index],
    )


def _load_config_payload(config_path: Path = CONFIG_PATH) -> dict[str, str]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "api_key": "",
                    "base_url": "",
                    "model": DEFAULT_MODEL,
                    "effort": DEFAULT_EFFORT,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("配置文件格式错误：根节点必须是对象。")
    return payload


def _save_config_payload(payload: dict[str, str], config_path: Path = CONFIG_PATH) -> None:
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def handle() -> bool:
    try:
        payload = _load_config_payload()
    except Exception as exc:
        print_text("error", f"读取配置失败: {exc}\n")
        return False

    current_model = str(payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    current_effort = str(payload.get("effort") or DEFAULT_EFFORT).strip() or DEFAULT_EFFORT

    model_candidates = list(dict.fromkeys([current_model, *MODEL_OPTIONS]))
    effort_candidates = list(dict.fromkeys([current_effort, *EFFORT_OPTIONS]))

    try:
        print_title_and_content("ai", "请选择要使用的模型：", title="Select Model")
        model = _select_from_options(
            options=model_candidates,
            default_index=model_candidates.index(current_model),
        )

        print_title_and_content("ai", "请选择推理强度：", title="Select Effort")

        effort = _select_from_options(
            options=effort_candidates,
            default_index=effort_candidates.index(current_effort),
        )
    except KeyboardInterrupt:
        return False

    payload["model"] = model
    payload["effort"] = effort

    try:
        _save_config_payload(payload)
    except Exception as exc:
        print_text("error", f"保存配置失败: {exc}\n")
        return False

    print_title_and_content("ai", f"已切换配置:\nmodel: {model}\neffort: {effort}\n\n", title="Model Updated")
    return False
