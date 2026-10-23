from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest


def test_official_mcp_sdk_stdio_client():
    """Runs only when the official MCP Python SDK is explicitly available."""
    mcp = pytest.importorskip("mcp")
    Client = mcp.Client
    StdioServerParameters = mcp.StdioServerParameters

    async def exercise():
        project_root = Path(__file__).parents[1].resolve()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(project_root / "src")
        server = StdioServerParameters(command=sys.executable, args=["-m", "shutu_atlas.cli", "mcp", "serve", "--transport", "stdio"], env=env)
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "atlas_health" in names
            health = await client.call_tool("atlas_health", {})
            assert not getattr(health, "is_error", False)

    asyncio.run(exercise())

