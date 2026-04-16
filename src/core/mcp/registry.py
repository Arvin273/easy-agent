from __future__ import annotations

import asyncio
import json
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Callable

from core.config.config_manager import MCPServerConfig


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPToolBinding:
    tool_name: str
    handler: Callable[[dict[str, Any]], Any]
    definition: dict[str, Any]


@dataclass
class _ServerConnection:
    name: str
    session: Any


class _MCPEventLoopThread:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ea-mcp-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


class MCPRegistry:
    def __init__(self) -> None:
        self._loop_thread: _MCPEventLoopThread | None = None
        self._tool_defs: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._config_key: str | None = None
        self._errors: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def initialize(self, servers: list[MCPServerConfig]) -> bool:
        next_key = self._build_config_key(servers)
        if next_key == self._config_key:
            return False

        self.close()
        self._errors = []
        self._tool_defs = []
        self._handlers = {}
        self._config_key = next_key

        if not servers:
            return True

        sdk = self._load_sdk()
        if sdk is None:
            self._errors.append(
                "检测到已配置 MCP server，但当前环境未安装 `mcp` 依赖。请先重新执行 `pip install -e .`。"
            )
            return True

        self._loop_thread = _MCPEventLoopThread()
        for server in servers:
            try:
                bindings = self._loop_thread.run(self._connect_server(server, sdk))
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"MCP server `{server.name}` 初始化失败: {exc}")
                continue
            for binding in bindings:
                self._tool_defs.append(binding.definition)
                self._handlers[binding.tool_name] = binding.handler
        return True

    def get_tools(self) -> list[dict[str, Any]]:
        return list(self._tool_defs)

    def get_handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return dict(self._handlers)

    def close(self) -> None:
        if self._loop_thread is not None:
            try:
                self._loop_thread.run(self._shutdown_async())
            except Exception:
                pass
            self._loop_thread.stop()
        self._loop_thread = None
        self._tool_defs = []
        self._handlers = {}

    async def _shutdown_async(self) -> None:
        exit_stack = getattr(self, "_exit_stack", None)
        if exit_stack is not None:
            await exit_stack.aclose()
            self._exit_stack = None

    def _load_sdk(self) -> dict[str, Any] | None:
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore[import-not-found]
            from mcp.client.sse import sse_client  # type: ignore[import-not-found]
            from mcp.client.stdio import stdio_client  # type: ignore[import-not-found]
            from mcp.client.streamable_http import streamable_http_client  # type: ignore[import-not-found]
        except ImportError:
            return None
        return {
            "ClientSession": ClientSession,
            "StdioServerParameters": StdioServerParameters,
            "stdio_client": stdio_client,
            "sse_client": sse_client,
            "streamable_http_client": streamable_http_client,
        }

    async def _connect_server(self, server: MCPServerConfig, sdk: dict[str, Any]) -> list[MCPToolBinding]:
        if not hasattr(self, "_exit_stack") or self._exit_stack is None:
            self._exit_stack = AsyncExitStack()

        session = await self._open_session(server, sdk)
        tools_result = await session.list_tools()
        tools = getattr(tools_result, "tools", [])
        bindings: list[MCPToolBinding] = []
        for tool in tools:
            raw_name = str(getattr(tool, "name", "")).strip()
            if not raw_name:
                continue
            tool_name = self._tool_name(server.name, raw_name)
            description = str(getattr(tool, "description", "") or "").strip()
            input_schema = self._tool_schema(tool)
            bindings.append(
                MCPToolBinding(
                    tool_name=tool_name,
                    handler=self._build_handler(server, session, raw_name),
                    definition={
                        "type": "function",
                        "name": tool_name,
                        "description": self._merge_description(server.name, raw_name, description),
                        "parameters": input_schema,
                    },
                )
            )
        return bindings

    async def _open_session(self, server: MCPServerConfig, sdk: dict[str, Any]) -> Any:
        exit_stack: AsyncExitStack = self._exit_stack
        if server.transport == "stdio":
            params = sdk["StdioServerParameters"](
                command=server.command,
                args=server.args,
                env=server.env or None,
            )
            read_stream, write_stream = await exit_stack.enter_async_context(sdk["stdio_client"](params))
        elif server.transport == "sse":
            read_stream, write_stream = await exit_stack.enter_async_context(
                sdk["sse_client"](server.url, headers=server.headers or None)
            )
        elif server.transport == "streamable_http":
            streamable_result = await exit_stack.enter_async_context(
                sdk["streamable_http_client"](server.url, headers=server.headers or None)
            )
            if not isinstance(streamable_result, tuple) or len(streamable_result) < 2:
                raise MCPError("streamable_http_client 返回值格式不正确。")
            read_stream, write_stream = streamable_result[0], streamable_result[1]
        else:
            raise MCPError(f"不支持的 MCP transport: {server.transport}")

        session = await exit_stack.enter_async_context(sdk["ClientSession"](read_stream, write_stream))
        await session.initialize()
        return session

    def _build_handler(self, server: MCPServerConfig, session: Any, remote_tool_name: str) -> Callable[[dict[str, Any]], Any]:
        def _handler(arguments: dict[str, Any]) -> str:
            if self._loop_thread is None:
                raise MCPError(f"MCP server `{server.name}` 当前未连接。")
            result = self._loop_thread.run(session.call_tool(remote_tool_name, arguments=arguments))
            return self._format_tool_result(result)

        return _handler

    def _format_tool_result(self, result: Any) -> str:
        blocks = getattr(result, "content", None)
        if isinstance(blocks, list) and blocks:
            texts: list[str] = []
            for block in blocks:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    texts.append(str(getattr(block, "text", "")))
                    continue
                if block_type == "image":
                    mime_type = getattr(block, "mimeType", "") or getattr(block, "mime_type", "")
                    texts.append(f"[image:{mime_type or 'unknown'}]")
                    continue
                texts.append(self._safe_json(block))
            merged = "\n".join([text for text in texts if text.strip()])
            if merged.strip():
                return merged

        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)
        if structured is not None:
            return self._safe_json(structured)
        return self._safe_json(result)

    def _tool_schema(self, tool: Any) -> dict[str, Any]:
        schema = getattr(tool, "inputSchema", None)
        if schema is None:
            schema = getattr(tool, "input_schema", None)
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump(mode="json")
        elif hasattr(schema, "dict"):
            schema = schema.dict()
        if isinstance(schema, dict) and schema.get("type") == "object":
            return schema
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    def _merge_description(self, server_name: str, remote_name: str, description: str) -> str:
        prefix = f"MCP server `{server_name}` 提供的工具 `{remote_name}`。"
        return prefix if not description else f"{prefix} {description}"

    def _tool_name(self, server_name: str, tool_name: str) -> str:
        return f"mcp__{self._sanitize_name(server_name)}__{self._sanitize_name(tool_name)}"

    def _sanitize_name(self, value: str) -> str:
        cleaned = [char.lower() if char.isalnum() else "_" for char in value]
        text = "".join(cleaned).strip("_")
        return text or "tool"

    def _safe_json(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            elif hasattr(value, "dict"):
                value = value.dict()
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(value)

    def _build_config_key(self, servers: list[MCPServerConfig]) -> str:
        payload = [server.to_dict() for server in servers]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
