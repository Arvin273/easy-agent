from __future__ import annotations

import sys
import time

from core.terminal.cli_output import ANSI_ENABLED


def _clear_input_line(prompt: str, buffer_len: int) -> None:
    sys.stdout.write("\r")
    if ANSI_ENABLED:
        sys.stdout.write("\x1b[2K")
    else:
        sys.stdout.write(" " * (len(prompt) + buffer_len + 2))
        sys.stdout.write("\r")
    sys.stdout.write(prompt)
    sys.stdout.flush()


def _render_input_line(prompt: str, text: str, previous_len: int) -> int:
    sys.stdout.write("\r")
    if ANSI_ENABLED:
        sys.stdout.write("\x1b[2K")
    else:
        width = max(previous_len, len(text))
        sys.stdout.write(" " * (len(prompt) + width + 2))
        sys.stdout.write("\r")
    sys.stdout.write(prompt)
    sys.stdout.write(text)
    sys.stdout.flush()
    return len(text)


def _read_user_input_windows(prompt: str, history: list[str] | None = None) -> str:
    import msvcrt

    history_items = history or []
    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    rendered_len = 0
    esc_pending = False
    last_esc_time = 0.0
    history_index: int | None = None
    draft_before_history = ""

    while True:
        ch = msvcrt.getwch()

        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buffer)
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\x00", "\xe0"):
            nav_key = msvcrt.getwch()
            if nav_key == "H" and history_items:  # up
                if history_index is None:
                    draft_before_history = "".join(buffer)
                    history_index = len(history_items) - 1
                elif history_index > 0:
                    history_index -= 1
                buffer = list(history_items[history_index])
                rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
            elif nav_key == "P" and history_items:  # down
                if history_index is None:
                    continue
                if history_index < len(history_items) - 1:
                    history_index += 1
                    buffer = list(history_items[history_index])
                else:
                    history_index = None
                    buffer = list(draft_before_history)
                rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
            esc_pending = False
            continue
        if ch == "\x1b":
            now = time.monotonic()
            if esc_pending and (now - last_esc_time) <= 0.6:
                buffer_len = len(buffer)
                buffer = []
                esc_pending = False
                _clear_input_line(prompt, buffer_len)
                rendered_len = 0
            else:
                esc_pending = True
                last_esc_time = now
            continue

        esc_pending = False
        history_index = None
        if ch in ("\b", "\x7f"):
            if buffer:
                buffer.pop()
                rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
            continue

        buffer.append(ch)
        rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)


def _read_user_input_posix(prompt: str, history: list[str] | None = None) -> str:
    import select
    import termios
    import tty

    history_items = history or []
    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    rendered_len = 0
    esc_pending = False
    last_esc_time = 0.0
    history_index: int | None = None
    draft_before_history = ""
    stdin = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin)
    try:
        tty.setraw(stdin)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x1b":
                ready, _, _ = select.select([sys.stdin], [], [], 0.02)
                if ready:
                    second = sys.stdin.read(1)
                    if second == "[":
                        third_ready, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if third_ready:
                            third = sys.stdin.read(1)
                            if third == "A" and history_items:  # up
                                if history_index is None:
                                    draft_before_history = "".join(buffer)
                                    history_index = len(history_items) - 1
                                elif history_index > 0:
                                    history_index -= 1
                                buffer = list(history_items[history_index])
                                rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
                                esc_pending = False
                                continue
                            if third == "B" and history_items:  # down
                                if history_index is None:
                                    esc_pending = False
                                    continue
                                if history_index < len(history_items) - 1:
                                    history_index += 1
                                    buffer = list(history_items[history_index])
                                else:
                                    history_index = None
                                    buffer = list(draft_before_history)
                                rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
                                esc_pending = False
                                continue
                now = time.monotonic()
                if esc_pending and (now - last_esc_time) <= 0.6:
                    buffer_len = len(buffer)
                    buffer = []
                    esc_pending = False
                    _clear_input_line(prompt, buffer_len)
                    rendered_len = 0
                else:
                    esc_pending = True
                    last_esc_time = now
                continue

            esc_pending = False
            history_index = None
            if ch in ("\x7f", "\b"):
                if buffer:
                    buffer.pop()
                    rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
                continue

            buffer.append(ch)
            rendered_len = _render_input_line(prompt, "".join(buffer), rendered_len)
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, old_settings)


def read_user_input(prompt: str, history: list[str] | None = None) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)
    if sys.platform.startswith("win"):
        return _read_user_input_windows(prompt, history=history)
    return _read_user_input_posix(prompt, history=history)

