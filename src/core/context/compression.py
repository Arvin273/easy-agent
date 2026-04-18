from __future__ import annotations

import json
from typing import Any

from openai import OpenAI
from core.utils.history_items import build_user_message


def _count_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_count_chars(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_chars(item) for item in value.values())
    return len(str(value))


def estimate_tokens(messages: list[dict[str, Any] | Any]) -> int:
    total = 0
    for item in messages:
        if not isinstance(item, dict):
            total += _count_chars(item)
            continue

        item_type = str(item.get("type") or "")
        if item_type == "function_call":
            total += _count_chars(item.get("name"))
            total += _count_chars(item.get("arguments"))
            total += _count_chars(item.get("call_id"))
            continue

        if item_type == "function_call_output":
            total += _count_chars(item.get("call_id"))
            total += _count_chars(item.get("output"))
            continue

        if item_type == "reasoning":
            total += _count_chars(item.get("id"))
            total += _count_chars(item.get("summary"))
            total += _count_chars(item.get("content"))
            continue

        if item_type == "message":
            total += _count_chars(item.get("role"))
            total += _count_chars(item.get("content"))
            continue

        total += _count_chars(item.get("role"))
        total += _count_chars(item.get("content"))

    return total


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


def _split_with_safe_recent_messages(
    messages: list[dict[str, Any] | Any],
    keep_recent_messages_count: int,
) -> tuple[list[dict[str, Any] | Any], list[dict[str, Any] | Any]]:
    if keep_recent_messages_count <= 0:
        return messages, []

    start_index = max(0, len(messages) - keep_recent_messages_count)
    preserved_indexes = set(range(start_index, len(messages)))

    call_index_by_id: dict[str, int] = {}
    output_indexes_by_id: dict[str, list[int]] = {}
    for index, item in enumerate(messages):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        call_id = str(item.get("call_id") or "")
        if not call_id:
            continue
        if item_type == "function_call":
            call_index_by_id[call_id] = index
        elif item_type == "function_call_output":
            output_indexes_by_id.setdefault(call_id, []).append(index)

    changed = True
    while changed:
        changed = False
        for index in list(preserved_indexes):
            item = messages[index]
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            call_id = str(item.get("call_id") or "")
            if not call_id:
                continue
            if item_type == "function_call_output":
                call_index = call_index_by_id.get(call_id)
                if call_index is not None and call_index not in preserved_indexes:
                    preserved_indexes.add(call_index)
                    changed = True
            elif item_type == "function_call":
                for output_index in output_indexes_by_id.get(call_id, []):
                    if output_index not in preserved_indexes:
                        preserved_indexes.add(output_index)
                        changed = True

    # 剔除孤立的 function_call_output，避免 API 报 call_id 关联错误。
    for index in list(preserved_indexes):
        item = messages[index]
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        call_id = str(item.get("call_id") or "")
        call_index = call_index_by_id.get(call_id)
        if not call_id or call_index is None or call_index not in preserved_indexes:
            preserved_indexes.remove(index)

    to_compact: list[dict[str, Any] | Any] = []
    preserved_recent: list[dict[str, Any] | Any] = []
    for index, item in enumerate(messages):
        if index in preserved_indexes:
            preserved_recent.append(item)
        else:
            to_compact.append(item)
    return to_compact, preserved_recent


def compact_history(
    client: OpenAI,
    model: str,
    history: list[dict[str, Any] | Any],
    focus: str | None = None,
    keep_recent_messages_count: int = 0,
) -> list[dict[str, Any]]:
    preserved_system = _leading_system_messages(history)
    non_system_messages: list[dict[str, Any] | Any] = history[len(preserved_system):]
    to_compact, preserved_recent = _split_with_safe_recent_messages(
        non_system_messages,
        keep_recent_messages_count=keep_recent_messages_count,
    )

    if not to_compact:
        return [*preserved_system, *preserved_recent]

    prompt = compact_prompt(to_compact, focus=focus)
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

    compressed_note = (
        "[Conversation compressed]\n\n"
        f"{summary}"
    )
    return [*preserved_system, build_user_message(compressed_note), *preserved_recent]
