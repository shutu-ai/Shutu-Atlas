from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shutu_atlas.discovery import discover_projects
from shutu_atlas.index.database import IndexStore


def test_local_project_reuse_skill_real_mcp_e2e(test_config):
    """Follow local-project-reuse against a real old project, then run a new one."""

    mcp = pytest.importorskip("mcp")
    Client = mcp.Client
    StdioServerParameters = mcp.StdioServerParameters

    repo_root = Path(__file__).parents[1].resolve()
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    old_project = next(item for item in projects if item.name == "fixture-python")

    # This is the selected disposable target project.  No source fixture or old
    # project is modified by the Skill workflow.
    target = test_config.project_root / "skill-reuse-target"
    target.mkdir(parents=True, exist_ok=True)
    app = target / "app.py"
    app.write_text(
        "def resume_from_checkpoint(job_id, checkpoints):\n"
        "    return checkpoints.get(job_id, {\"status\": \"restart recovery required\"})\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    print(resume_from_checkpoint(\"job-1\", {\"job-1\": {\"status\": \"resumed\"}}))\n",
        encoding="utf-8",
    )

    config_path = test_config.project_root / "skill-e2e.toml"
    config_path.write_text(
        "[paths]\n"
        f'db = "{test_config.db_path.as_posix()}"\n'
        f'gallery = "{test_config.gallery_dir.as_posix()}"\n'
        f'serena_workspaces = "{test_config.serena_dir.as_posix()}"\n'
        "[scan]\n"
        f'roots = ["{test_config.roots[0].as_posix()}"]\n',
        encoding="utf-8",
    )

    async def call_real_mcp():
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            str(path)
            for path in (repo_root / ".local" / "python-deps", repo_root / "src")
            if path.exists()
        )
        server = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "shutu_atlas.cli",
                "--config",
                str(config_path),
                "mcp",
                "serve",
                "--transport",
                "stdio",
            ],
            env=env,
            cwd=str(repo_root),
        )

        async def decode(result):
            raw = getattr(result, "structured_content", None)
            if isinstance(raw, dict):
                return raw
            text = next((getattr(block, "text", "") for block in getattr(result, "content", [])), "")
            return json.loads(text)

        async with Client(server, read_timeout_seconds=30.0) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {
                "atlas_health",
                "atlas_find_capability",
                "atlas_search_code",
                "atlas_get_source",
            }
            assert required <= names

            health = await decode(await client.call_tool("atlas_health", {}))
            assert health["status"] in {"ok", "ready"}

            listed = await decode(await client.call_tool("atlas_list_projects", {"limit": 10}))
            assert any(item["project_id"] == old_project.project_id for item in listed["results"])

            capabilities = await decode(
                await client.call_tool(
                    "atlas_find_capability",
                    {"query": "recover_after_restart", "limit": 3, "project_filter": old_project.project_id},
                )
            )
            assert capabilities["results"]

            search = await decode(
                await client.call_tool(
                    "atlas_search_code",
                    {"query": "recover_after_restart", "limit": 3, "project_id": old_project.project_id},
                )
            )
            assert search["results"]
            evidence = search["results"][0]
            source = await decode(
                await client.call_tool(
                    "atlas_get_source",
                    {
                        "project_id": old_project.project_id,
                        "file_id": evidence["file_id"],
                        # FTS results identify the file but not a line; the
                        # fixture's matching method is below the first page.
                        "start_line": max(1, evidence.get("line", 13)),
                    },
                )
            )
            assert source["status"] == "ok"
            assert "recover_after_restart" in source["text"]

    try:
        asyncio.run(call_real_mcp())
    except (PermissionError, OSError) as exc:
        pytest.skip(f"official MCP stdio subprocess unavailable in this environment: {exc}")

    completed = subprocess.run(
        [sys.executable, str(app)],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "resumed" in completed.stdout
