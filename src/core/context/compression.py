from __future__ import annotations

import json
from typing import Any

from openai import OpenAI


def estimate_tokens(messages: list[dict[str, Any] | Any]) -> int:
    try:
        payload = json.dumps(messages, ensure_ascii=False, default=str)
    except Exception:
        payload = str(messages)
    return max(1, len(payload) // 4)


def micro_compact(
    history: list[dict[str, Any] | Any],
    keep_recent_tool_outputs: int,
    min_compact_output_length: int,
) -> None:
    tool_outputs: list[dict[str, Any]] = []
    call_to_tool: dict[str, str] = {}

    for item in history:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            call_id = str(item.get("call_id") or "")
            tool_name = str(item.get("name") or "unknown")
            if call_id:
                call_to_tool[call_id] = tool_name
        if item.get("type") == "function_call_output":
            tool_outputs.append(item)

    if len(tool_outputs) <= keep_recent_tool_outputs:
        return

    to_compact = tool_outputs[:-keep_recent_tool_outputs]
    for output_item in to_compact:
        output_text = output_item.get("output")
        if not isinstance(output_text, str) or len(output_text) <= min_compact_output_length:
            continue
        call_id = str(output_item.get("call_id") or "")
        tool_name = call_to_tool.get(call_id, "unknown")
        output_item["output"] = f"[Previous: used {tool_name}]"


def compact_prompt(messages: list[dict[str, Any] | Any], focus: str | None = None) -> str:
    conversation_text = json.dumps(messages, ensure_ascii=False, default=str)
    focus_text = f"\n额外关注点：{focus}\n" if focus else "\n"
    return (
        "请将下面会话压缩为可持续继续工作的上下文摘要。"
        "必须包含："
        "1) 已完成事项；"
        "2) 当前状态与未完成任务；"
        "3) 关键决策与约束；"
        "4) 用户明确偏好。"
        "摘要要精炼，但不能丢失关键可执行信息。"
        f"{focus_text}\n"
        "会话内容如下：\n"
        f"{conversation_text}"
    )


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "output_text":
                text = getattr(content, "text", "")
                if text:
                    chunks.append(str(text))
    return "\n".join(chunks).strip()


def _leading_system_messages(history: list[dict[str, Any] | Any]) -> list[dict[str, Any]]:
    preserved: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            break
        if item.get("role") != "system":
            break
        preserved.append(item)
    return preserved


def compact_history(
    client: OpenAI,
    model: str,
    history: list[dict[str, Any] | Any],
    focus: str | None = None,
) -> list[dict[str, Any]]:
    prompt = compact_prompt(history, focus=focus)
    summary = "No summary generated."
    try:
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=1800,
            reasoning={"effort": "low"},
        )
        summary_text = _extract_output_text(response)
        if summary_text:
            summary = summary_text
    except Exception as exc:
        summary = f"Summary failed: {exc}"

    preserved_system = _leading_system_messages(history)
    compressed_note = (
        "[Conversation compressed]\n\n"
        f"{summary}"
    )
    return [*preserved_system, {"role": "user", "content": compressed_note}]
