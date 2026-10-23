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
repositories or user Codex/OpenCode configuration. The Atlas MCP process now
resolves `serena.exe`, `uv.exe`, and `uvx.exe` beside its active Python before
falling back to PATH, and passes that venv directory only to the Hub-owned
Serena child process.

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

```toml
[mcp_servers.shutu-atlas]
command = "D:/dev-projects/Shutu-Atlas/.local/integration-venv/Scripts/python.exe"
args = ["-m", "shutu_atlas.cli", "--config", "D:/dev-projects/Shutu-Atlas/atlas.toml", "mcp", "serve", "--transport", "stdio"]

[mcp_servers.shutu-atlas.env]
PYTHONPATH = "D:/dev-projects/Shutu-Atlas/src"
```

This is a mergeable Codex `config.toml` entry. Back up the user file first and
preserve all other `[mcp_servers.*]` sections. The absolute Python path is
intentional: it makes the official SDK and Serena selection reproducible in a
new conversation without relying on a one-shot PowerShell PATH change.

OpenCode remains `UNVERIFIED`: the CLI was present, but the environment
rejected its log-file open with `EPERM`, so no authenticated client session or
user-level configuration change was attempted.

## Final real Codex CLI evidence

On 2026-10-23 the real `codex exec` CLI was run in the fresh Git target
`.local/codex-e2e-20261023-retry` with a one-shot MCP configuration override;
the user's `C:\Users\swx1536744\.codex\config.toml` was not changed. Codex
loaded `skills/local-project-reuse/SKILL.md` and called `atlas_health`,
`atlas_find_capability`, `atlas_search_code`, and `atlas_get_source` through
the Shutu-Atlas stdio server.

The selected evidence was
`D:\dev-projects\English-Practice\benchmark.go:362-373`,
project_id `aeac851c36b9a320`, file_id `2329`, Git HEAD
`f80ceeee2b7932ccaba962f942c00a71ee850078`, branch `main`. The exact code
search returned no `recover_after_restart` implementation; the bounded source
range contained only a `PostProbeRecovery` metric field at line 366. Codex
classified the capability as `inferred/unverified` and did not claim reuse.
It created only `reused_app.py` and `test_reused_app.py` in the disposable
target and ran `python -m pytest -q` with 4 passing tests.

The first attempt was intentionally recorded as blocked because it overlapped
the active SQLite writer and returned `database is locked` during MCP
initialization. After run 20 completed, direct MCP initialize and the full
Codex sequence succeeded. This is why the retry evidence is the authoritative
Agent acceptance record.
