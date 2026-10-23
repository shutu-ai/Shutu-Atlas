from __future__ import annotations

import json
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
            capability = self.store.find_capability(requirement, min(limit, 3))
            ui = self.store.find_ui(requirement, min(limit, 3))
            return {"status": "ok", "source": "indexed-evidence", "requirement": requirement, "target_stack": args.get("target_stack"), "candidates": capability.get("results", [])[:3], "ui_candidates": ui.get("results", [])[:3], "reuse_types": ["reuse_direct", "adapt", "visual_reference", "unknown"], "warnings": ["候选是静态证据；实施前请用 atlas_get_source 核验依赖、许可证和测试"]}
        if name == "atlas_health":
            result = self.store.status()
            result["rg"] = {"available": __import__("shutil").which("rg") is not None}
            result["serena"] = self.serena.health()
            result["mcp_sdk"] = {"available": __import__("importlib.util").util.find_spec("mcp") is not None, "mode": "compat-stdio"}
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


def run_stdio(cfg: AtlasConfig) -> None:
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

