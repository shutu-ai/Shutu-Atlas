from __future__ import annotations

import json
import importlib.util
import asyncio
import sys
from typing import Any

from ..config import AtlasConfig
from ..index.database import IndexStore
from ..symbols.providers import FallbackProvider, SerenaProvider


PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "atlas_list_projects", "description": "列出已索引的真实项目", "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}}}},
    {"name": "atlas_find_capability", "description": "按能力和证据查找候选实现", "inputSchema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "project_filter": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}}}},
    {"name": "atlas_search_code", "description": "使用 FTS5 与 ripgrep 搜索代码", "inputSchema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "mode": {"type": "string"}, "project_id": {"type": "string"}, "language": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}}}},
    {"name": "atlas_find_symbol", "description": "查找符号定义；Serena 不可用时返回降级状态", "inputSchema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "project_id": {"type": "string"}, "kind": {"type": "string"}}}},
    {"name": "atlas_get_source", "description": "读取已索引文件的受限源码片段", "inputSchema": {"type": "object", "required": ["project_id", "file_id"], "properties": {"project_id": {"type": "string"}, "file_id": {"type": "integer"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}}},
    {"name": "atlas_find_ui", "description": "搜索 UI 页面、组件、样式和截图状态", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "project_id": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}}}},
    {"name": "atlas_get_ui_detail", "description": "读取 UI 资产与源码映射详情", "inputSchema": {"type": "object", "required": ["asset_id"], "properties": {"asset_id": {"type": "string"}}}},
    {"name": "atlas_suggest_reuse", "description": "根据已有证据给出复用候选与适配提示", "inputSchema": {"type": "object", "required": ["requirement"], "properties": {"requirement": {"type": "string"}, "target_stack": {"type": "string"}, "limit": {"type": "integer", "maximum": 3}}}},
    {"name": "atlas_health", "description": "报告索引、ripgrep、Serena 和图库健康状态", "inputSchema": {"type": "object", "properties": {}}},
]


class McpService:
    def __init__(self, cfg: AtlasConfig):
        self.store = IndexStore(cfg)
        self.serena = SerenaProvider(cfg, FallbackProvider(self.store))

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(1, int(args.get("limit", 10))), 50)
        if name == "atlas_list_projects":
            return {"status": "ok", "source": "sqlite", "results": self.store.list_projects(args.get("filter"), limit), "warnings": []}
        if name == "atlas_find_capability":
            return self.store.find_capability(str(args.get("query", "")), limit, args.get("project_filter"))
        if name == "atlas_search_code":
            return self.store.search_code(str(args.get("query", "")), limit, args.get("project_id"), args.get("language"))
        if name == "atlas_find_symbol":
            return self.serena.find_symbol(str(args.get("name", "")), args.get("project_id"), args.get("kind"))
        if name == "atlas_get_source":
            return self.store.get_source(str(args.get("project_id", "")), int(args.get("file_id", 0)), int(args.get("start_line", 1)), args.get("end_line"))
        if name == "atlas_find_ui":
            return self.store.find_ui(str(args.get("query", "")), limit, args.get("project_id"))
        if name == "atlas_get_ui_detail":
            return self.store.ui_detail(str(args.get("asset_id", "")))
        if name == "atlas_suggest_reuse":
            requirement = str(args.get("requirement", ""))
            return self.store.suggest_reuse(requirement, args.get("target_stack"), min(limit, 3))
        if name == "atlas_health":
            result = self.store.status()
            result["rg"] = {"available": __import__("shutil").which("rg") is not None}
            result["serena"] = self.serena.health()
            sdk_available = official_sdk_available()
            result["mcp_sdk"] = {
                "available": sdk_available,
                "mode": "official-lowlevel" if sdk_available else "compat-stdio",
            }
            result["gallery"] = {"path": str(self.store.cfg.gallery_dir), "read_only_api": True}
            return result
        raise ValueError(f"unknown tool: {name}")


def _response(request_id: Any, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def handle_message(service: McpService, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _response(request_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": "shutu-atlas", "version": "0.2.0"}})
    if method in {"notifications/initialized", "notifications/cancelled", "ping"}:
        return None if method.startswith("notifications/") else _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        try:
            params = message.get("params", {})
            data = service.call(str(params.get("name", "")), params.get("arguments") or {})
            return _response(request_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data, "isError": data.get("status") in {"error", "denied", "not_found"}})
        except Exception as exc:
            return _response(request_id, error={"code": -32602, "message": f"{type(exc).__name__}: {exc}"})
    if request_id is not None:
        return _response(request_id, error={"code": -32601, "message": f"method not found: {method}"})
    return None


def official_sdk_available() -> bool:
    """Return whether the installed MCP package is available to the process."""

    return importlib.util.find_spec("mcp") is not None


def _run_official_stdio(cfg: AtlasConfig) -> None:
    """Run the read-only server through the current official Python SDK.

    Imports stay lazy so the standard-library compatibility transport remains
    usable on a clean Windows installation.  This implementation follows the
    v2 low-level SDK API: constructor-registered handlers and ``stdio_server``.
    """

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolRequestParams,
        CallToolResult,
        ListToolsResult,
        PaginatedRequestParams,
        TextContent,
        Tool,
    )

    service = McpService(cfg)
    sdk_tools = [
        Tool(
            name=tool["name"],
            description=tool["description"],
            input_schema=tool["inputSchema"],
        )
        for tool in TOOLS
    ]

    async def list_tools(_ctx: Any, _params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=sdk_tools)

    async def call_tool(_ctx: Any, params: CallToolRequestParams) -> CallToolResult:
        try:
            data = service.call(params.name, params.arguments or {})
        except Exception as exc:
            data = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
            structured_content=data,
            is_error=data.get("status") in {"error", "denied", "not_found"},
        )

    server = Server("shutu-atlas", on_list_tools=list_tools, on_call_tool=call_tool)

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(serve())


def _run_compat_stdio(cfg: AtlasConfig) -> None:
    """Run the dependency-free JSON-RPC compatibility transport."""

    service = McpService(cfg)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            result = handle_message(service, message)
            if result is not None:
                sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            print(f"invalid JSON-RPC input: {exc}", file=sys.stderr)


def run_stdio(cfg: AtlasConfig) -> None:
    """Prefer the official SDK and retain a truthful dependency-free fallback."""

    if official_sdk_available():
        _run_official_stdio(cfg)
    else:
        _run_compat_stdio(cfg)

