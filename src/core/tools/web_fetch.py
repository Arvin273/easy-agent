from __future__ import annotations

import re
from typing import Any

from core.tools.web_utils import fetch_url_content, run_small_model

TOOL_NAME = "WebFetch"


def _extract_html_title(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return re.sub(r"^#+\s*", "", stripped).strip()
    return ""


def _build_fetch_result(url: str, prompt: str, fetched: Any) -> str:
    if fetched.redirect_url:
        result = (
            "REDIRECT DETECTED\n"
            f"- 原 URL: {url}\n"
            f"- 重定向后 URL: {fetched.redirect_url}\n"
            "请使用新的 URL 再调用一次 WebFetch。"
        )
    elif fetched.binary_path:
        result = (
            "抓取到的是二进制内容，未直接提取文本。\n"
            f"- URL: {fetched.url}\n"
            f"- Content-Type: {fetched.content_type or '(unknown)'}\n"
            f"- Bytes: {fetched.bytes_count}\n"
            f"- 已保存到: {fetched.binary_path}"
        )
    elif not fetched.text:
        result = "网页内容为空。"
    else:
        title_prefix = ""
        if "html" in fetched.content_type:
            title = _extract_html_title(fetched.text)
            if title:
                title_prefix = f"页面标题：{title}\n\n"
        result = run_small_model(
            prompt=(
                "请严格基于给定网页内容完成任务。"
                "如果内容不足以回答，就明确说信息不足。"
                "引用链接时使用 markdown 超链接。"
                f"\n\n用户任务：{prompt}"
            ),
            content=f"URL: {fetched.url}\nContent-Type: {fetched.content_type}\n\n{title_prefix}{fetched.text}",
            system_prompt=(
                "你是一个网页内容提取助手。"
                "只基于提供的网页内容回答，不要补充未出现的信息。"
                "输出简洁，必要时保留原文中的关键术语。"
            ),
        )

    header = [
        f"URL: {fetched.url or url}",
        f"HTTP Status: {fetched.status_code}",
        f"Content-Type: {fetched.content_type or '(unknown)'}",
        f"Bytes: {fetched.bytes_count}",
    ]
    if prompt.strip():
        header.append(f"Prompt: {prompt.strip()}")
    return "\n".join(header) + "\n\nResult:\n" + result.strip()


def run_web_fetch(arguments: dict[str, Any]) -> str:
    url = arguments.get("url")
    prompt = arguments.get("prompt")

    if not isinstance(url, str) or not url.strip():
        raise ValueError("缺少有效的 url 参数。")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("缺少有效的 prompt 参数。")

    try:
        fetched = fetch_url_content(url)
        return _build_fetch_result(url=url, prompt=prompt, fetched=fetched)
    except Exception as exc:
        return f"Error: {exc}"


TOOL_HANDLER = run_web_fetch
TOOL_DEF = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "抓取公开网页内容，并根据 prompt 提取信息。"
        "\n\n"
        "使用规则：\n"
        "- 传入完整的 URL 和明确的 prompt，例如“总结这篇文章的主要观点”或“提取安装步骤”\n"
        "- 只适合公开可访问网页；需要登录、私有权限或专用 API 的地址通常会失败\n"
        "- 如果网页跳转到其他域名，工具会返回新的 URL，之后应使用新 URL 重新调用\n"
        "- 对 PDF 等二进制内容，工具会保存原文件到本地，并返回保存路径\n"
        "- 回答必须基于抓取到的网页内容，不要把它当作通用联网搜索工具\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "description": "要抓取的公开网页 URL",
                "type": "string",
            },
            "prompt": {
                "description": "你希望从该网页中提取什么信息",
                "type": "string",
            },
        },
        "required": ["url", "prompt"],
        "additionalProperties": False,
    },
}
