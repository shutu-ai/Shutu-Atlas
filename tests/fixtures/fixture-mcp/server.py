"""Static cross-stack fixture for MCP transport and progress evidence."""

import json


TOOLS = [{"name": "task_status", "description": "Read task progress"}]


async def list_tools():
    """Expose the stdio tool list without mutating the source project."""
    return TOOLS


async def call_tool(name: str, arguments: dict):
    """Handle a read-only task status request."""
    if name != "task_status":
        raise ValueError(name)
    return json.dumps({"task_id": arguments.get("task_id"), "progress": 1.0})


def streamable_http_endpoint(host: str = "127.0.0.1", port: int = 8765) -> str:
    """Return the configured Streamable HTTP endpoint for documentation/tests."""
    return f"http://{host}:{port}/mcp"
