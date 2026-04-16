from __future__ import annotations

import sys
from typing import TypeVar

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition, is_done, renderer_height_is_known
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_bindings import DynamicKeyBindings, merge_key_bindings
from prompt_toolkit.layout import AnyContainer, ConditionalContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.shortcuts.choice_input import create_default_choice_input_style
from prompt_toolkit.styles import BaseStyle, Style
from prompt_toolkit.widgets import Box, Label, RadioList
from prompt_toolkit.document import Document

from core.terminal.cli_output import THEME

T = TypeVar("T")

_CHOICE_BINDINGS = KeyBindings()
_CHOICE_TOOLBAR = "↑/↓ 选择，Enter 确认，Ctrl+C 取消"
_TEXT_PROMPT_STYLE = Style.from_dict(
    {
        "input.shell": "#ff5faf",
        "slash-menu.command": "#5fd7ff",
        "slash-menu.command.current": "bold #00afaf",
        "slash-menu.desc": "#9a9a9a",
        "slash-menu.desc.current": "#6f8f8f",
    }
)


@_CHOICE_BINDINGS.add("j")
@_CHOICE_BINDINGS.add("k")
def _ignore_vi_navigation(event: object) -> None:
    return None


def _build_history(history: list[str] | None = None) -> InMemoryHistory:
    prompt_history = InMemoryHistory()
    for item in history or []:
        if item.strip():
            prompt_history.append_string(item)
    return prompt_history


class PrefixCommandCompleter(Completer):
    def __init__(self, command_descriptions: dict[str, str]) -> None:
        self._command_descriptions = dict(sorted(command_descriptions.items()))

    def get_completions(self, document: Document, complete_event: object):
        text = document.text_before_cursor
        for command, description in self.get_matches(text):
            yield Completion(
                text=command,
                start_position=-len(text.strip()),
                display=command,
                display_meta=description,
            )

    def get_matches(self, text: str) -> list[tuple[str, str]]:
        normalized = text.strip()
        if not normalized or " " in normalized:
            return []
        if not (normalized.startswith("/") or normalized.startswith("$")):
            return []
        prefix = normalized.lower()
        return [
            (command, description)
            for command, description in self._command_descriptions.items()
            if command.startswith(prefix)
        ]


def _get_completion_menu_text(buffer: Buffer) -> str:
    completion_state = buffer.complete_state
    if completion_state is not None:
        return completion_state.original_document.text
    return buffer.text


def _has_valid_completion_state(buffer: Buffer) -> bool:
    completion_state = buffer.complete_state
    if completion_state is None:
        return False
    completions = completion_state.completions
    if not completions:
        return False
    index = completion_state.complete_index
    if index is None:
        return True
    return 0 <= index < len(completions)


def _has_completion_matches(buffer: Buffer, completer: PrefixCommandCompleter) -> bool:
    return bool(completer.get_matches(_get_completion_menu_text(buffer)))


def _clear_completion_state(buffer: Buffer) -> None:
    buffer.complete_state = None


def _cancel_completion_safely(buffer: Buffer) -> None:
    if _has_valid_completion_state(buffer):
        buffer.cancel_completion()
        return
    _clear_completion_state(buffer)


def _is_prefix_input_context(buffer: Buffer) -> bool:
    text = buffer.text.strip()
    return (text.startswith("/") or text.startswith("$")) and " " not in text


def _is_dollar_skill_selection_context(buffer: Buffer) -> bool:
    text = buffer.text.strip()
    return text.startswith("$") and " " not in text


def _get_input_style(buffer: Buffer) -> str:
    if buffer.text.lstrip().startswith("!"):
        return "class:input.shell"
    return ""


def _refresh_completion(buffer: Buffer, completer: PrefixCommandCompleter) -> None:
    if not _is_prefix_input_context(buffer):
        _cancel_completion_safely(buffer)
        return
    if completer.get_matches(buffer.text):
        buffer.start_completion(
            select_first=False,
            complete_event=CompleteEvent(text_inserted=False, completion_requested=False),
        )
        return
    _cancel_completion_safely(buffer)


def _ensure_valid_completion_navigation(buffer: Buffer, completer: PrefixCommandCompleter) -> bool:
    if not _is_prefix_input_context(buffer):
        _cancel_completion_safely(buffer)
        return False
    if not _has_completion_matches(buffer, completer):
        _cancel_completion_safely(buffer)
        return False
    if not _has_valid_completion_state(buffer):
        _refresh_completion(buffer, completer)
    if not _has_valid_completion_state(buffer):
        _clear_completion_state(buffer)
        return False
    return True


def _apply_selected_completion(buffer: Buffer, completion: Completion) -> None:
    completed_text = completion.text
    buffer.set_document(
        Document(text=completed_text, cursor_position=len(completed_text)),
        bypass_readonly=True,
    )
    _clear_completion_state(buffer)


def _build_text_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("c-u")
    def _clear_current_input(event: object) -> None:
        event.current_buffer.reset()

    @bindings.add("c-c")
    @bindings.add("<sigint>")
    def _handle_ctrl_c(event: object) -> None:
        if _clear_input_on_interrupt(event.current_buffer):
            return
        event.app.exit(exception=KeyboardInterrupt())

    return bindings


def _clear_input_on_interrupt(buffer: Buffer) -> bool:
    if not buffer.text:
        return False
    buffer.reset()
    return True


def _render_completion_menu(
    buffer: Buffer,
    completer: PrefixCommandCompleter,
    max_items: int = 8,
):
    matches = completer.get_matches(_get_completion_menu_text(buffer))
    if not matches:
        return []

    completion_state = buffer.complete_state
    current_index = 0
    if completion_state is not None and completion_state.complete_index is not None:
        current_index = completion_state.complete_index
    current_index = min(current_index, len(matches) - 1)

    start = min(max(0, current_index), max(0, len(matches) - max_items))
    visible_matches = matches[start:start + max_items]
    command_width = max(len(command) for command, _ in visible_matches)

    fragments: list[tuple[str, str]] = []
    for index, (command, description) in enumerate(visible_matches):
        is_current = (start + index) == current_index
        command_style = (
            "class:slash-menu.command.current" if is_current else "class:slash-menu.command"
        )
        desc_style = "class:slash-menu.desc.current" if is_current else "class:slash-menu.desc"
        command_text = command.ljust(command_width + 2)
        fragments.append((command_style, command_text))
        if description:
            fragments.append((desc_style, description))
        if index < len(visible_matches) - 1:
            fragments.append(("", "\n"))
    return fragments


def _run_text_prompt(
    *,
    prompt: str,
    default: str,
    history: InMemoryHistory,
    completer: Completer | None,
    complete_while_typing: bool,
) -> str:
    if completer is None:
        session = PromptSession(history=history)
        result = session.prompt(
            prompt,
            default=default,
            key_bindings=_build_text_bindings(),
        )
        return result

    document = Document(text=default, cursor_position=len(default))
    buffer = Buffer(
        completer=completer,
        history=history,
        complete_while_typing=complete_while_typing,
        multiline=False,
        document=document,
    )

    def _ensure_first_completion(_: Buffer) -> None:
        completion_state = buffer.complete_state
        if completion_state is None or not completion_state.completions:
            return
        if completion_state.complete_index is None:
            completion_state.go_to_index(0)
            return
        if completion_state.complete_index >= len(completion_state.completions):
            completion_state.go_to_index(len(completion_state.completions) - 1)

    buffer.on_completions_changed += _ensure_first_completion

    input_window = Window(
        BufferControl(
            buffer=buffer,
            input_processors=[BeforeInput(prompt)],
            focus_on_click=True,
        ),
        style=lambda: _get_input_style(buffer),
        dont_extend_height=True,
        wrap_lines=True,
    )

    show_completion_menu = Condition(lambda: _has_completion_matches(buffer, completer))

    completion_menu = ConditionalContainer(
        VSplit(
            [
                Window(width=Dimension.exact(len(prompt)), char=" "),
                Window(
                    FormattedTextControl(
                        lambda: _render_completion_menu(buffer, completer)
                    ),
                    dont_extend_width=True,
                    dont_extend_height=True,
                    height=Dimension(max=8),
                ),
            ]
        ),
        filter=show_completion_menu,
    )

    layout = Layout(
        HSplit(
            [
                input_window,
                Window(height=Dimension.exact(1), char=" "),
                completion_menu,
            ]
        ),
        focused_element=input_window,
    )

    bindings = _build_text_bindings()

    @bindings.add("up", eager=True)
    def _history_previous(event: object) -> None:
        if _ensure_valid_completion_navigation(buffer, completer):
            buffer.complete_previous()
            return
        _cancel_completion_safely(buffer)
        event.current_buffer.auto_up(count=event.arg)

    @bindings.add("down", eager=True)
    def _history_next(event: object) -> None:
        if _ensure_valid_completion_navigation(buffer, completer):
            buffer.complete_next()
            return
        _cancel_completion_safely(buffer)
        event.current_buffer.auto_down(count=event.arg)

    @bindings.add("tab", filter=show_completion_menu, eager=True)
    def _select_next_completion(event: object) -> None:
        if _ensure_valid_completion_navigation(buffer, completer):
            buffer.complete_next()

    @bindings.add("s-tab", filter=show_completion_menu, eager=True)
    def _select_previous_completion(event: object) -> None:
        if _ensure_valid_completion_navigation(buffer, completer):
            buffer.complete_previous()

    @bindings.add("backspace", filter=Condition(lambda: _is_prefix_input_context(buffer)), eager=True)
    def _delete_and_refresh_completion(event: object) -> None:
        buffer.delete_before_cursor(count=1)
        _refresh_completion(buffer, completer)

    @bindings.add("delete", filter=Condition(lambda: _is_prefix_input_context(buffer)), eager=True)
    def _forward_delete_and_refresh_completion(event: object) -> None:
        buffer.delete(count=1)
        _refresh_completion(buffer, completer)

    @bindings.add("enter", eager=True)
    def _submit_input(event: object) -> None:
        completion_state = buffer.complete_state
        current_completion = None
        if completion_state is not None:
            idx = completion_state.complete_index
            completions = completion_state.completions
            if idx is not None and 0 <= idx < len(completions):
                current_completion = completions[idx]
        if current_completion is not None:
            if _is_prefix_input_context(buffer):
                _apply_selected_completion(buffer, current_completion)
                return
            buffer.apply_completion(current_completion)
        if _is_dollar_skill_selection_context(buffer):
            return
        event.app.exit(result=buffer.text)

    app = Application(
        layout=layout,
        key_bindings=bindings,
        full_screen=False,
        style=_TEXT_PROMPT_STYLE,
        erase_when_done=True,
    )
    return app.run()


def read_text(
    prompt: str,
    history: list[str] | None = None,
    default: str = "",
    command_descriptions: dict[str, str] | None = None,
    echo_result: bool = True,
) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)

    prompt_history = _build_history(history)
    completer = None
    if command_descriptions:
        completer = PrefixCommandCompleter(command_descriptions)
    result = _run_text_prompt(
        prompt=prompt,
        default=default,
        history=prompt_history,
        completer=completer,
        complete_while_typing=bool(command_descriptions),
    )
    if echo_result:
        print(f"{prompt}{result}\n")
    return result


def read_user_input(
    prompt: str,
    history: list[str] | None = None,
    command_descriptions: dict[str, str] | None = None,
) -> str:
    return read_text(prompt, history=history, command_descriptions=command_descriptions)


def _run_choice(
    *,
    message: str,
    options: list[tuple[T, str]],
    default: T | None,
    bottom_toolbar: AnyFormattedText,
    key_bindings: KeyBindings,
    style: BaseStyle | None = None,
) -> T:
    if style is None:
        style = create_default_choice_input_style()

    radio_list = RadioList(
        values=options,
        default=default,
        select_on_focus=True,
        open_character="",
        select_character=">",
        close_character="",
        show_cursor=False,
        show_numbers=True,
        container_style="class:input-selection",
        default_style="class:option",
        selected_style="",
        checked_style="class:selected-option",
        number_style="class:number",
        show_scrollbar=False,
    )

    content_parts: list[AnyContainer] = []
    if message:
        content_parts.append(
            Box(
                Label(text=message, dont_extend_height=True),
                padding_top=0,
                padding_left=1,
                padding_right=1,
                padding_bottom=0,
            )
        )
    content_parts.append(
        Box(
            radio_list,
            padding_top=0,
            padding_left=3,
            padding_right=1,
            padding_bottom=0,
        )
    )
    container: AnyContainer = HSplit(content_parts)

    show_bottom_toolbar = (
        Condition(lambda: bottom_toolbar is not None) & ~is_done & renderer_height_is_known
    )

    bottom_toolbar_container = ConditionalContainer(
        Window(
            FormattedTextControl(lambda: bottom_toolbar, style="class:bottom-toolbar.text"),
            style="class:bottom-toolbar",
            dont_extend_height=True,
            height=Dimension(min=1),
        ),
        filter=show_bottom_toolbar,
    )

    layout = Layout(
        HSplit(
            [
                container,
                ConditionalContainer(Window(), filter=show_bottom_toolbar),
                bottom_toolbar_container,
            ]
        ),
        focused_element=radio_list,
    )

    app_bindings = KeyBindings()

    @app_bindings.add("enter", eager=True)
    def _accept_input(event: object) -> None:
        event.app.exit(result=radio_list.current_value, style="class:accepted")

    @app_bindings.add("c-c")
    @app_bindings.add("<sigint>")
    def _keyboard_interrupt(event: object) -> None:
        event.app.exit(exception=KeyboardInterrupt(), style="class:aborting")

    app = Application(
        layout=layout,
        full_screen=False,
        key_bindings=merge_key_bindings(
            [app_bindings, DynamicKeyBindings(lambda: key_bindings)]
        ),
        style=style,
    )
    return app.run()


def select_option(
    options: list[tuple[T, str]],
    default: T | None = None,
    message: str = "",
) -> T:
    if not options:
        raise ValueError("options 不能为空。")

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        if default is not None:
            return default
        return options[0][0]

    result = _run_choice(
        message=f"{THEME.body_indent}{message}" if message else "",
        options=options,
        default=default,
        bottom_toolbar=f"{THEME.body_indent}{_CHOICE_TOOLBAR}",
        key_bindings=_CHOICE_BINDINGS,
    )
    print()
    return result
