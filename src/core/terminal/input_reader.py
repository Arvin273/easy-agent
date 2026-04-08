from __future__ import annotations

import sys
import time
import unicodedata

from core.terminal.cli_output import ANSI_ENABLED


def _display_width(text: str) -> int:
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        if unicodedata.east_asian_width(ch) in {"W", "F"}:
            width += 2
        else:
            width += 1
    return width


def _clear_input_line(prompt: str, buffer_width: int) -> None:
    sys.stdout.write("\r")
    if ANSI_ENABLED:
        sys.stdout.write("\x1b[2K")
    else:
        sys.stdout.write(" " * (len(prompt) + buffer_width + 2))
        sys.stdout.write("\r")
    sys.stdout.write(prompt)
    sys.stdout.flush()


def _render_input_line(prompt: str, text: str, cursor: int, previous_width: int) -> int:
    text_width = _display_width(text)
    cursor_width = _display_width(text[:cursor])
    sys.stdout.write("\r")
    if ANSI_ENABLED:
        sys.stdout.write("\x1b[2K")
    else:
        width = max(previous_width, text_width)
        sys.stdout.write(" " * (len(prompt) + width + 2))
        sys.stdout.write("\r")
    sys.stdout.write(prompt)
    sys.stdout.write(text)
    if ANSI_ENABLED:
        right_gap = max(0, text_width - cursor_width)
        if right_gap:
            sys.stdout.write(f"\x1b[{right_gap}D")
    sys.stdout.flush()
    return text_width


def _read_user_input_windows(prompt: str, history: list[str] | None = None) -> str:
    import msvcrt

    history_items = history or []
    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    cursor = 0
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
                cursor = len(buffer)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key == "P" and history_items:  # down
                if history_index is None:
                    continue
                if history_index < len(history_items) - 1:
                    history_index += 1
                    buffer = list(history_items[history_index])
                else:
                    history_index = None
                    buffer = list(draft_before_history)
                cursor = len(buffer)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key == "K":  # left
                cursor = max(0, cursor - 1)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key == "M":  # right
                cursor = min(len(buffer), cursor + 1)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key in {"G"}:  # home
                cursor = 0
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key in {"O"}:  # end
                cursor = len(buffer)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            elif nav_key == "S":  # delete
                if cursor < len(buffer):
                    buffer.pop(cursor)
                    rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            esc_pending = False
            continue
        if ch == "\x1b":
            now = time.monotonic()
            if esc_pending and (now - last_esc_time) <= 0.6:
                buffer = []
                cursor = 0
                esc_pending = False
                _clear_input_line(prompt, rendered_len)
                rendered_len = 0
            else:
                esc_pending = True
                last_esc_time = now
            continue

        esc_pending = False
        history_index = None
        if ch in ("\b", "\x7f"):
            if cursor > 0 and buffer:
                cursor -= 1
                buffer.pop(cursor)
                rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
            continue

        buffer.insert(cursor, ch)
        cursor += 1
        rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)


def _read_user_input_posix(prompt: str, history: list[str] | None = None) -> str:
    import select
    import termios
    import tty

    history_items = history or []
    sys.stdout.write(prompt)
    sys.stdout.flush()

    buffer: list[str] = []
    cursor = 0
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
                        seq = ""
                        for _ in range(8):
                            piece_ready, _, _ = select.select([sys.stdin], [], [], 0.02)
                            if not piece_ready:
                                break
                            piece = sys.stdin.read(1)
                            seq += piece
                            if piece.isalpha() or piece == "~":
                                break
                        if seq == "A" and history_items:  # up
                            if history_index is None:
                                draft_before_history = "".join(buffer)
                                history_index = len(history_items) - 1
                            elif history_index > 0:
                                history_index -= 1
                            buffer = list(history_items[history_index])
                            cursor = len(buffer)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq == "B" and history_items:  # down
                            if history_index is None:
                                esc_pending = False
                                continue
                            if history_index < len(history_items) - 1:
                                history_index += 1
                                buffer = list(history_items[history_index])
                            else:
                                history_index = None
                                buffer = list(draft_before_history)
                            cursor = len(buffer)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq == "C":  # right
                            cursor = min(len(buffer), cursor + 1)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq == "D":  # left
                            cursor = max(0, cursor - 1)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq in {"H", "1~", "7~", "1;2H", "1;2~"}:  # home (+shift variants)
                            cursor = 0
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq in {"F", "4~", "8~", "1;2F", "4;2~"}:  # end (+shift variants)
                            cursor = len(buffer)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                        if seq == "3~":  # delete
                            if cursor < len(buffer):
                                buffer.pop(cursor)
                            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                            esc_pending = False
                            continue
                now = time.monotonic()
                if esc_pending and (now - last_esc_time) <= 0.6:
                    buffer = []
                    cursor = 0
                    esc_pending = False
                    _clear_input_line(prompt, rendered_len)
                    rendered_len = 0
                else:
                    esc_pending = True
                    last_esc_time = now
                continue

            esc_pending = False
            history_index = None
            if ch in ("\x7f", "\b"):
                if cursor > 0 and buffer:
                    cursor -= 1
                    buffer.pop(cursor)
                    rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
                continue

            buffer.insert(cursor, ch)
            cursor += 1
            rendered_len = _render_input_line(prompt, "".join(buffer), cursor, rendered_len)
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, old_settings)


def read_user_input(prompt: str, history: list[str] | None = None) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)
    if sys.platform.startswith("win"):
        return _read_user_input_windows(prompt, history=history)
    return _read_user_input_posix(prompt, history=history)
