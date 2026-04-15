from __future__ import annotations

from datetime import datetime

from core.terminal.cli_output import Colors, print_text, print_title_and_content, print_marked_text
from core.tools.bash import get_background_bash_tasks

COMMAND = "/jobs"
DESCRIPTION = "查看后台 Bash 任务"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def handle(args: list[str]) -> bool:
    include_output = False
    status_filter: set[str] | None = None
    task_id: str | None = None

    for arg in args:
        if arg == "--output":
            include_output = True
            continue
        if arg == "--running":
            status_filter = {"running"}
            continue
        if arg == "--done":
            status_filter = {"completed", "failed", "timed_out", "cancelled"}
            continue
        if arg.startswith("--"):
            print_marked_text(content=f"Unknown jobs option: {arg}\n\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
            return False
        if task_id is not None:
            print_marked_text(content="用法错误：/jobs 只支持一个 task_id。\n\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
            return False
        task_id = arg

    tasks = get_background_bash_tasks(task_id=task_id, include_output=include_output)
    if status_filter is not None:
        tasks = [task for task in tasks if str(task.get("status")) in status_filter]

    if include_output and task_id is None:
        print_marked_text(content="用法错误：/jobs --output 需要配合 task_id 使用。\n\n", marker="■", body_color=Colors.error, marker_color=Colors.error)
        return False

    if not tasks:
        print_text(Colors.reason, "当前没有匹配的后台 Bash 任务。\n\n")
        return False

    if task_id is None and not include_output:
        lines = []
        for task in tasks:
            desc = str(task.get("description") or task.get("command") or "").strip()
            status = str(task.get("status") or "-")
            return_code = task.get("return_code")
            suffix = f" exit={return_code}" if return_code is not None else ""
            lines.append(f"- {task['task_id']} [{status}{suffix}] {desc}")
        print_title_and_content(Colors.green, "\n".join(lines) + "\n\n", title="Background Jobs")
        return False

    task = tasks[0]
    lines = [
        f"task_id: {task['task_id']}",
        f"status: {task.get('status', '-')}",
        f"return_code: {task.get('return_code', '-')}",
        f"started_at: {_format_timestamp(task.get('started_at'))}",
        f"finished_at: {_format_timestamp(task.get('finished_at'))}",
        f"description: {task.get('description') or '-'}",
        f"command: {task.get('command') or '-'}",
    ]
    preview = str(task.get("preview") or "").strip()
    if include_output:
        output = str(task.get("output") or "(no output)")
        lines.extend(["", "output:", output])
    elif preview:
        lines.extend(["", "preview:", preview])
    print_title_and_content(Colors.green, "\n".join(lines) + "\n\n", title="Background Job")
    return False
