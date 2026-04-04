import json
import os
import subprocess
import threading
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from core.cli_output import format_tool_call, print_box
from core.builtin_tools import DEFAULT_MODEL, TOOL_HANDLERS, TOOLS, WORKDIR

load_dotenv()


class BackgroundManager:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self._notification_queue: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "status": "running",
            "result": None,
            "command": command,
        }
        worker = threading.Thread(
            target=self._execute,
            args=(task_id, command),
            daemon=True,
        )
        worker.start()
        return f"Background task {task_id} started: {command[:80]}"

    def _execute(self, task_id: str, command: str) -> None:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=WORKDIR,
                capture_output=True,
                timeout=300,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            output = (stdout + stderr).strip()[:50000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output = "Error: Timeout (300s)"
            status = "timeout"
        except Exception as exc:
            output = f"Error: {exc}"
            status = "error"

        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output or "(no output)"
        with self._lock:
            self._notification_queue.append(
                {
                    "task_id": task_id,
                    "status": status,
                    "command": command,
                    "result": (output or "(no output)")[:500],
                }
            )

    def check(self, task_id: str | None = None) -> str:
        if task_id:
            task = self.tasks.get(task_id)
            if task is None:
                return f"Error: Unknown task {task_id}"
            return (
                f"[{task['status']}] {task['command'][:60]}\n"
                f"{task.get('result') or '(running)'}"
            )

        lines = []
        for tid, task in self.tasks.items():
            lines.append(f"{tid}: [{task['status']}] {task['command'][:60]}")
        return "\n".join(lines) if lines else "No background tasks."

    def drain_notifications(self) -> list[dict[str, str]]:
        with self._lock:
            notifications = list(self._notification_queue)
            self._notification_queue.clear()
        return notifications


BG = BackgroundManager()


def run_background(arguments: dict[str, Any]) -> str:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少有效的 command 参数。")
    return BG.run(command)


def run_check_background(arguments: dict[str, Any]) -> str:
    task_id = arguments.get("task_id")
    if task_id is not None and not isinstance(task_id, str):
        raise ValueError("task_id 参数必须是字符串。")
    return BG.check(task_id)


LOCAL_TOOL_HANDLERS = {
    **TOOL_HANDLERS,
    "background_run": run_background,
    "check_background": run_check_background,
}

LOCAL_TOOLS = [
    *TOOLS,
    {
        "type": "function",
        "name": "background_run",
        "description": "在后台线程执行 shell 命令，立即返回任务 ID。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要在后台执行的命令"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "check_background",
        "description": "查询后台任务状态；不传 task_id 时返回全部任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": ["string", "null"],
                    "description": "后台任务 ID，可选",
                },
            },
            "additionalProperties": False,
        },
    },
]


def print_response_items(response: Any) -> list[Any]:
    tool_calls: list[Any] = []

    for item in response.output:
        if item.type != "reasoning":
            continue
        for summary_item in item.summary or []:
            text = getattr(summary_item, "text", "")
            if text:
                print_box("reason", text, title="REASON")

    for item in response.output:
        if item.type != "message":
            continue
        for content_item in item.content:
            if getattr(content_item, "type", None) != "output_text":
                continue
            text = getattr(content_item, "text", "")
            if text:
                print_box("ai", text, title="AI")

    for item in response.output:
        if item.type == "function_call":
            tool_calls.append(item)

    return tool_calls


def run_tool_call(tool_call: Any) -> dict[str, str]:
    tool_name = tool_call.name
    arguments = json.loads(tool_call.arguments)
    print_box(
        "tool_calling",
        format_tool_call({"name": tool_name, "args": arguments}),
        title="Tool Calling",
    )
    handler = LOCAL_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        result = f"Unknown tool: {tool_name}"
    else:
        try:
            result = handler(arguments)
        except Exception as exc:
            result = f"Tool '{tool_name}' failed: {exc}"

    print_box("tool", result, title="Tool Result")
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": result,
    }


def agent_loop(
    client: OpenAI,
    model: str,
    history: list[dict[str, Any] | Any],
) -> None:
    while True:
        notifications = BG.drain_notifications()
        if notifications:
            notification_text = "\n".join(
                f"[bg:{item['task_id']}] {item['status']}: {item['result']}"
                for item in notifications
            )
            history.append(
                {
                    "role": "user",
                    "content": (
                        "<background-results>\n"
                        f"{notification_text}\n"
                        "</background-results>"
                    ),
                }
            )

        response = client.responses.create(
            model=model,
            input=history,
            tools=LOCAL_TOOLS,
            reasoning={"effort": "high", "summary": "concise"},
        )
        history.extend(response.output)
        tool_calls = print_response_items(response)
        if not tool_calls:
            return

        tool_outputs = [run_tool_call(tool_call) for tool_call in tool_calls]
        history.extend(tool_outputs)


def main() -> None:
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        http_client=httpx.Client(verify=False),
    )
    model = os.getenv("MODEL_ID", DEFAULT_MODEL)

    history: list[dict[str, Any] | Any] = [
        {
            "role": "system",
            "content": (
                "你是一个agent。"
                "你可以调用工具来解决问题。"
                "在调用工具时，务必生成一段文字来说明你要做什么。"
                "对于耗时命令，优先使用 background_run，并在后续通过 check_background 或等待后台通知获取结果。"
            ),
        }
    ]

    while True:
        try:
            query = input("user> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.lower() in {"", "q", "exit"}:
            break

        print_box("user", query, title="USER")
        history.append({"role": "user", "content": query})
        agent_loop(client=client, model=model, history=history)


if __name__ == "__main__":
    main()

