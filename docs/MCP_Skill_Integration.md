# MCP and local-project-reuse Skill integration

## Read-only MCP stdio

Shutu-Atlas exposes a read-only stdio service. It prefers the official MCP
Python SDK when that optional dependency is available and otherwise keeps the
dependency-free JSON-RPC compatibility transport.

```powershell
atlas mcp serve --transport stdio
```

The server exposes query-only tools: project listing, capability/UI search,
code/symbol/source lookup, reuse suggestions, and health. It does not expose
index refresh, shell execution, Git writes, source writes, or Gallery writes.

The verified integration lock is:

```text
mcp[cli]==2.2.0
serena-agent==2.1.0
uv==0.13.5
```

`mcp==2.2.0` is intentional: Serena 2.1.0 declares that exact MCP version.
`uv` is required by Serena's official Python language-server bootstrap.

The isolated verification environment is kept under `.local/integration-venv`.
It is not the user's default Python environment and does not write source
repositories or user Codex/OpenCode configuration.

## Evidence commands

```powershell
python -m pytest -q
$env:PATH = "D:\dev-projects\Shutu-Atlas\.local\integration-venv\Scripts;$env:PATH"
python -m pytest -q tests/test_mcp_sdk_optional.py tests/test_serena_optional.py tests/test_skill_e2e.py
python -m pytest -q tests/test_gallery_frontend.py
```

The elevated integration run used the official `mcp.Client` stdio client,
listed the real Atlas tools, called `atlas_health`, queried a real indexed
fixture, fetched a bounded source range, and ran the disposable target project
created by `tests/test_skill_e2e.py`. Serena was started against a Hub-owned
mirror with `SERENA_HOME`, `UV_CACHE_DIR`, and all integration state under
`.local`; no source project received a `.serena` directory.

## Skill workflow

`skills/local-project-reuse/SKILL.md` requires this sequence:

1. call `atlas_health`;
2. query only the relevant capability/UI candidates;
3. use code/symbol search to identify evidence and line ranges;
4. read a bounded source range and inspect stack/dependency/risk evidence;
5. classify the result as `reuse_direct`, `adapt`, `visual_reference`,
   `not_recommended`, or `unknown`;
6. change only the explicitly selected new project and run its test.

The automated E2E test follows that sequence against `fixture-python` and then
runs a minimal `resume_from_checkpoint` feature in a fresh disposable target.

## Client configuration

Users may merge the following server entry into their client configuration
after backing it up. The project never overwrites an existing user config.

```json
{
  "mcpServers": {
    "shutu-atlas": {
      "command": "D:/dev-projects/Shutu-Atlas/.venv/Scripts/python.exe",
      "args": ["-m", "shutu_atlas.cli", "mcp", "serve", "--transport", "stdio"],
      "cwd": "D:/dev-projects/Shutu-Atlas"
    }
  }
}
```

OpenCode remains `UNVERIFIED`: the CLI was present, but the environment
rejected its log-file open with `EPERM`, so no authenticated client session or
user-level configuration change was attempted.
