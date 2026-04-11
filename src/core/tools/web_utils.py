from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from openai import OpenAI

from core.config.config_manager import PATHS, load_agent_config

CACHE_TTL_SECONDS = 15 * 60
USER_AGENT = "easy-agent/1.0"
MAX_MODEL_INPUT_CHARS = 50000
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE: dict[str, tuple[float, "FetchedWebContent"]] = {}


@dataclass(frozen=True)
class FetchedWebContent:
    url: str
    status_code: int
    content_type: str
    bytes_count: int
    text: str | None = None
    binary_path: str | None = None
    redirect_url: str | None = None


def normalize_web_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("缺少有效的 url 参数。")
    stripped = url.strip()
    parsed = urlparse(stripped)
    if not parsed.scheme:
        raise ValueError("url 必须是完整的 URL。")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url 只支持 http 或 https。")
    if not parsed.netloc:
        raise ValueError("url 必须包含有效主机。")
    return parsed.geturl()


def get_hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_authenticated_or_private_url(url: str) -> bool:
    host = get_hostname(url)
    blocked_hosts = {
        "docs.google.com",
        "drive.google.com",
        "github.com",
    }
    blocked_suffixes = (
        ".atlassian.net",
        ".jira.com",
        ".confluence.net",
    )
    return host in blocked_hosts or any(host.endswith(item) for item in blocked_suffixes)


def html_to_markdown(content: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", content)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</?(p|div|section|article|header|footer|main|aside|table|tr|ul|ol|pre|blockquote)>", "\n", cleaned)
    cleaned = re.sub(r"(?i)<li[^>]*>", "\n- ", cleaned)
    cleaned = re.sub(r"(?i)</li>", "", cleaned)
    for level in range(1, 7):
        cleaned = re.sub(rf"(?i)<h{level}[^>]*>", "\n" + ("#" * level) + " ", cleaned)
        cleaned = re.sub(rf"(?i)</h{level}>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", "", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _store_binary_content(url: str, response: httpx.Response) -> str:
    target_dir = PATHS.local_ea_dir / "web_fetch"
    target_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".bin"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", parsed.netloc + parsed.path)
    safe_name = safe_name.strip("._") or "download"
    timestamp = int(time.time())
    file_path = target_dir / f"{safe_name}.{timestamp}{suffix}"
    file_path.write_bytes(response.content)
    return str(file_path)


def fetch_url_content(url: str) -> FetchedWebContent:
    normalized_url = normalize_web_url(url)
    if is_authenticated_or_private_url(normalized_url):
        raise ValueError("这个 URL 很可能需要登录或私有访问，请改用带认证能力的专用工具。")

    now = time.time()
    with _FETCH_CACHE_LOCK:
        stale_keys = [cache_key for cache_key, (created_at, _) in _FETCH_CACHE.items() if now - created_at > CACHE_TTL_SECONDS]
        for stale_key in stale_keys:
            _FETCH_CACHE.pop(stale_key, None)
        cached = _FETCH_CACHE.get(normalized_url)
        if cached is not None:
            created_at, value = cached
            if now - created_at <= CACHE_TTL_SECONDS:
                return value
            _FETCH_CACHE.pop(normalized_url, None)

    with httpx.Client(follow_redirects=False, timeout=20, verify=False, headers={"User-Agent": USER_AGENT}) as client:
        current_url = normalized_url
        for _ in range(5):
            response = client.get(current_url)
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    raise ValueError(f"URL 重定向失败: {current_url}")
                next_url = normalize_web_url(urljoin(current_url, location))
                if get_hostname(next_url) != get_hostname(current_url):
                    redirected = FetchedWebContent(
                        url=current_url,
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        bytes_count=0,
                        redirect_url=next_url,
                    )
                    with _FETCH_CACHE_LOCK:
                        _FETCH_CACHE[normalized_url] = (time.time(), redirected)
                    return redirected
                current_url = next_url
                continue

            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            bytes_count = len(response.content)

            is_textual = any(
                item in content_type
                for item in (
                    "text/",
                    "application/json",
                    "application/xml",
                    "application/javascript",
                    "application/xhtml+xml",
                )
            )
            is_markdown = "text/markdown" in content_type or current_url.lower().endswith((".md", ".markdown"))

            if is_textual:
                if is_markdown:
                    rendered = response.text
                elif "html" in content_type:
                    rendered = html_to_markdown(response.text)
                else:
                    rendered = response.text
                fetched = FetchedWebContent(
                    url=current_url,
                    status_code=response.status_code,
                    content_type=content_type,
                    bytes_count=bytes_count,
                    text=rendered.strip(),
                )
                with _FETCH_CACHE_LOCK:
                    _FETCH_CACHE[normalized_url] = (time.time(), fetched)
                return fetched

            binary_path = _store_binary_content(current_url, response)
            fetched = FetchedWebContent(
                url=current_url,
                status_code=response.status_code,
                content_type=content_type,
                bytes_count=bytes_count,
                binary_path=binary_path,
            )
            with _FETCH_CACHE_LOCK:
                _FETCH_CACHE[normalized_url] = (time.time(), fetched)
            return fetched

    raise ValueError(f"URL 重定向次数过多: {normalized_url}")


def run_small_model(prompt: str, content: str, system_prompt: str) -> str:
    config = load_agent_config()
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=httpx.Client(verify=False),
    )
    response = client.responses.create(
        model=config.model,
        input=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{prompt}\n\n以下是可用内容：\n\n{content[:MAX_MODEL_INPUT_CHARS]}",
            },
        ],
    )
    text = getattr(response, "output_text", "") or ""
    if text.strip():
        return text.strip()
    raise RuntimeError("模型未返回内容。")
