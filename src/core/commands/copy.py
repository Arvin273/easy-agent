from __future__ import annotations

import ctypes
import subprocess
import sys
from shutil import which
from typing import Any

from core.terminal.cli_output import Colors, print_text

COMMAND = "/copy"
DESCRIPTION = "复制最后一条 AI 回复"
CF_UNICODETEXT = 13


def _find_last_assistant_message(history: list[dict[str, Any] | Any] | None) -> str | None:
    if not history:
        return None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def _copy_to_clipboard(content: str) -> None:
    if sys.platform.startswith("win"):
        _copy_to_windows_clipboard(content)
        return

    if sys.platform == "darwin":
        subprocess.run(
            ["pbcopy"],
            input=content,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return

    for command in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if which(command[0]) is None:
            continue
        subprocess.run(
            command,
            input=content,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return

    raise RuntimeError("当前系统未找到可用的剪贴板命令。")


def _copy_to_windows_clipboard(content: str) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        raise RuntimeError("无法打开系统剪贴板。")

    global_memory = None
    try:
        if not user32.EmptyClipboard():
            raise RuntimeError("无法清空系统剪贴板。")

        data = content.encode("utf-16-le") + b"\x00\x00"
        global_memory = kernel32.GlobalAlloc(0x0002, len(data))
        if not global_memory:
            raise RuntimeError("无法为剪贴板分配内存。")

        locked_memory = kernel32.GlobalLock(global_memory)
        if not locked_memory:
            raise RuntimeError("无法锁定剪贴板内存。")
        try:
            ctypes.memmove(locked_memory, data, len(data))
        finally:
            kernel32.GlobalUnlock(global_memory)

        if not user32.SetClipboardData(CF_UNICODETEXT, global_memory):
            raise RuntimeError("无法写入系统剪贴板。")
        global_memory = None
    finally:
        if global_memory:
            kernel32.GlobalFree(global_memory)
        user32.CloseClipboard()


def handle(history: list[dict[str, Any] | Any] | None) -> bool:
    content = _find_last_assistant_message(history)
    if content is None:
        print_text(Colors.error, "当前会话里没有可复制的 AI 回复。\n\n")
        return False

    try:
        _copy_to_clipboard(content)
    except Exception as exc:
        print_text(Colors.error, f"复制失败: {exc}\n\n")
        return False

    print_text(Colors.green, "已复制最后一条 AI 回复到剪贴板。\n\n")
    return False
