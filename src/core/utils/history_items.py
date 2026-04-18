from __future__ import annotations

from typing import Any


def build_user_message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": text,
            }
        ],
    }

def build_developer_message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "developer",
        "content": [
            {
                "type": "input_text",
                "text": text,
            }
        ],
    }


def build_assistant_message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
            }
        ],
    }


def build_function_call_item(name: str, arguments: str, call_id: str) -> dict[str, str]:
    return {
        "type": "function_call",
        "name": name,
        "arguments": arguments,
        "call_id": call_id,
    }


def build_function_call_output_item(call_id: str, output: str) -> dict[str, str]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
    }
