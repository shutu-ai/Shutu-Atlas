from __future__ import annotations

from pathlib import Path

from shutu_atlas.discovery import discover_projects
from shutu_atlas.index.database import IndexStore
from shutu_atlas.mcp_server.server import McpService, handle_message
from shutu_atlas.symbols.providers import FallbackProvider, SerenaProvider, SerenaWorkspaceManager


def test_symbol_isolation_and_real_fallback(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    one = next(p for p in projects if p.name == "one")
    two = next(p for p in projects if p.name == "two")
    result_one = store.find_symbols("shared_symbol", one.project_id)
    result_two = store.find_symbols("shared_symbol", two.project_id)
    assert result_one["results"][0]["path"].endswith("fixture-multi-repo\\one")
    assert result_two["results"][0]["path"].endswith("fixture-multi-repo\\two")
    provider = SerenaProvider(test_config, FallbackProvider(store))
    assert provider.health()["status"] in {"BLOCKED_ENV", "AVAILABLE_UNVERIFIED"}
    mirror = SerenaWorkspaceManager(test_config).mirror(one)
    assert mirror.mirror_root.is_relative_to(test_config.serena_dir)
    assert not (Path(one.path) / ".serena").exists()


def test_mcp_read_only_tools(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    service = McpService(test_config)
    initialize = handle_message(service, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialize["result"]["serverInfo"]["name"] == "shutu-atlas"
    tools = handle_message(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "atlas_health" in names and "atlas_search_code" in names
    assert not any("write" in name or "exec" in name for name in names)
    call = handle_message(service, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "atlas_list_projects", "arguments": {"limit": 2}}})
    assert call["result"]["structuredContent"]["results"]
    health_call = handle_message(service, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "atlas_health", "arguments": {}}})
    health = health_call["result"]["structuredContent"]
    assert health["last_successful_index_at"]
    assert health["freshness"]["coverage_scope"] == "root"

