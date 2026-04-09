from typing import Any

from core.terminal.cli_output import THEME, print_title_and_content, Colors
from core.terminal.prompt_ui import read_text, select_option


def _select_option(options: list[str], default_index: int) -> int:
    pairs = [(index, option) for index, option in enumerate(options)]
    return select_option(
        options=pairs,
        default=default_index,
    )


def _ask_single_question(
    *,
    title: str,
    question_id: str,
    question_text: str,
    options: list[str],
    default_index: int,
) -> dict[str, Any]:
    allow_custom_input = True
    if default_index < 0 or default_index >= len(options):
        raise ValueError("default_index 超出 options 范围。")

    custom_option = "其他（自行输入）"
    selectable_options = options + [custom_option]

    print_title_and_content(
        color=Colors.user,
        title=title,
        content=question_text,
    )
    selected_index = _select_option(
        options=selectable_options,
        default_index=default_index,
    )

    is_custom = allow_custom_input and selected_index == len(options)
    if is_custom:
        user_input = read_text(
            f"{THEME.body_indent}输入你的答案并回车: ",
            echo_result=False,
        )
        print()
        return {
            "id": question_id,
            "question": question_text,
            "selected_index": selected_index,
            "selected_option": custom_option,
            "is_custom": True,
            "custom_input": user_input,
            "answer": user_input,
        }

    selected_option = options[selected_index]
    return {
        "id": question_id,
        "question": question_text,
        "selected_index": selected_index,
        "selected_option": selected_option,
        "is_custom": False,
        "custom_input": None,
        "answer": selected_option,
    }


def run_ask_user_question(arguments: dict[str, Any]) -> dict[str, str]:
    questions = arguments.get("questions")

    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 参数必须是非空数组。")

    normalized_questions: list[dict[str, Any]] = []
    for idx, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError("questions 中每一项都必须是对象。")
        question_text = item.get("question")
        options = item.get("options")
        default_index = item.get("default_index", 0)
        question_title = item.get("title")
        question_id = item.get("id") or f"q{idx}"

        if not isinstance(question_text, str) or not question_text.strip():
            raise ValueError("questions[].question 必须是非空字符串。")
        if not isinstance(options, list) or not options:
            raise ValueError("questions[].options 必须是非空字符串数组。")
        if any(not isinstance(option, str) or not option.strip() for option in options):
            raise ValueError("questions[].options 中每一项都必须是非空字符串。")
        if len(options) > 20:
            raise ValueError("questions[].options 最多支持 20 项。")
        if not isinstance(default_index, int):
            raise ValueError("questions[].default_index 必须是整数。")
        if not isinstance(question_title, str) or not question_title.strip():
            raise ValueError("questions[].title 必须是非空字符串。")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError("questions[].id 必须是非空字符串。")

        normalized_questions.append(
            {
                "id": question_id.strip(),
                "title": question_title.strip(),
                "question": question_text.strip(),
                "options": [opt.strip() for opt in options],
                "default_index": default_index,
            }
        )

    answers: list[dict[str, Any]] = []
    for item in normalized_questions:
        answer = _ask_single_question(
            title=item["title"],
            question_id=item["id"],
            question_text=item["question"],
            options=item["options"],
            default_index=item["default_index"],
        )
        answers.append(answer)

    display_lines = ["用户选择完毕："]
    for answer in answers:
        display_lines.append(f"- {answer['id']}: {answer['answer']}")
    display_text = "\n".join(display_lines)
    return {"output": display_text}


TOOL_NAME = "ask_user_question"
TOOL_HANDLER = run_ask_user_question
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "当你在执行过程中需要向用户提问时，请使用此工具。它可以帮助你：1. 收集用户偏好或需求 2. 澄清有歧义的指令 3. 在工作过程中获取用户对实现方案的决定 4. 为用户提供可选方向，让其作出选择",
    "parameters": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "问题列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "题目 ID，用于结果映射；不传则自动生成"},
                        "title": {"type": "string", "description": "该题的显示标题"},
                        "question": {"type": "string", "description": "问题内容"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "候选项列表（至少 1 项，最多 20 项）",
                        },
                        "default_index": {"type": "integer", "description": "默认选中下标，默认 0"},
                    },
                    "required": ["title", "question", "options"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
}
