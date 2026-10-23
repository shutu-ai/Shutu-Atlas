from __future__ import annotations

import asyncio
import importlib.util
import shutil
from pathlib import Path

import pytest

from shutu_atlas.discovery import discover_projects
from shutu_atlas.index.database import IndexStore
from shutu_atlas.symbols.providers import FallbackProvider, SerenaProvider, _run_async


def test_serena_sync_bridge_inside_event_loop():
    async def value():
        return 42

    async def invoke_from_handler():
        return _run_async(value)

    assert asyncio.run(invoke_from_handler()) == 42


def test_real_serena_symbol_integration(test_config):
    """Run the real isolated Serena path only when both dependencies exist."""

    if not shutil.which("serena"):
        pytest.skip("serena executable is not installed")
    if importlib.util.find_spec("mcp") is None:
        pytest.skip("official MCP Python SDK is not installed")

    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    project = next(item for item in projects if item.name == "fixture-python")
    result = SerenaProvider(test_config, FallbackProvider(store)).find_symbol("TaskStore", project.project_id)

    assert result["source"] == "serena"
    assert result["serena_health"]["status"] == "PASS"
    assert result["results"]
    assert not (Path(project.path) / ".serena").exists()
