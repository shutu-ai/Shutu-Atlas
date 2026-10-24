# Windows operations

## Base setup

```powershell
cd D:\dev-projects\Shutu-Atlas
.\scripts\install.ps1
Copy-Item atlas.example.toml atlas.toml
notepad atlas.toml
atlas doctor
```

The default install is offline-friendly. It writes only project-local files.
The configured default root is `D:\dev-projects`; `Shutu-Atlas` itself is
excluded from source discovery.

## Optional official integrations

Use the Hub-owned isolated environment when verifying Serena and the official
MCP SDK. The paths below are project-local; they do not modify system Python:

```powershell
$atlasPython = (Resolve-Path .local\integration-venv\Scripts\python.exe).Path
& $atlasPython -m pip install -r requirements-integrations.txt
$env:PATH = "$(Split-Path $atlasPython);$env:PATH"
& $atlasPython -m pytest -q tests/test_mcp_sdk_optional.py tests/test_serena_optional.py tests/test_skill_e2e.py
```

The pinned compatibility set is `mcp[cli]==2.2.0`,
`serena-agent==2.1.0`, and `uv==0.13.5`. Serena's `uv/uvx` cache and all
Serena mirrors/logs used by Shutu-Atlas are redirected into `.local`.

Do not install a Skill or edit a user's Codex/OpenCode configuration without
an explicit confirmation and a backup. The project-provided Skill installer
defaults to dry-run.

## Index lifecycle

```powershell
atlas scan --root D:\dev-projects --dry-run
atlas index --root D:\dev-projects
atlas index --changed-only
atlas status
```

The CLI records each run in `index_runs`, including mode, projects seen, files
indexed, errors, status, and owner PID. A killed run is marked `interrupted`;
an incomplete run must not be described as full coverage. Source projects are
never used as the storage location for the index or Serena state.

## Troubleshooting

- `Serena BLOCKED_ENV`: use the static symbol provider and record the missing
  executable/SDK. Never activate Serena in a source repository.
- `mcp_sdk BLOCKED_ENV`: the compatibility stdio transport remains available;
  run the optional tests in the isolated environment for official SDK evidence.
- `OpenCode UNVERIFIED`: the CLI or its user log/config permissions prevented a
  real client session; do not modify user state to force a PASS.
- `source denied`: confirm the path is indexed, text-readable, not sensitive,
  not under an excluded directory, and not a symlink/reparse point.
- `DB locked`: wait for the active index run and use read-only queries; do not
  delete an active database or journal.
- No screenshot: this is the safe default. Import an explicitly supplied
  image with `atlas gallery import-screenshot --asset-id ... --path ...`.

## V2 performance and recovery controls

Every scan/index result now includes stage timings and counters for discovery,
Git status, path checks, directory traversal, stat, SHA-256, source reads,
symbol/capability detection, SQLite writes, and FTS writes. Each project
checkpoint records file count, scanned bytes, skipped count, changed and
unchanged counts, elapsed time, status, and error details.

The ordinary changed-only path is stat-first:

```powershell
atlas index --changed-only
```

It compares stored size and nanosecond mtime and does not hash unchanged files.
Use the stronger content-validation mode when same-size/same-mtime rewrites are
possible:

```powershell
atlas index --changed-only --force-hash
```

The strong mode hashes every eligible file and is expected to be slower. A run
that is interrupted can be continued without repeating completed project
content indexing:

```powershell
atlas index --changed-only --resume
atlas index --changed-only --retry-project PROJECT_NAME_OR_ID
atlas status
```

`partial` is a real terminal status. The checked-in
`atlas.example.toml` and the local V2 `atlas.toml` set
`max_files_per_project = 30000` because the current inventory contains two
legitimate source/UI projects with 23k–24k eligible files. The Python default
remains a conservative 20,000 when no config file is supplied. Any project
that exceeds the active limit is recorded with its actual eligible file count,
bytes, skipped count, and `FileLimitReached` error; it must not be reported as
complete.

Cache/generated directories such as `.codegraph`, `.go-cache`,
`.go-mod-cache`, `.deploy-staging*`, and `pytest-cache-files-*` are excluded
from source traversal. This is a source-boundary/performance rule, not a
timeout.

## Nightly Auto Index

The Windows-only nightly wrapper is documented in
[`Nightly_Auto_Index.md`](Nightly_Auto_Index.md). It reuses the commands above
and does not change the V2 index engine:

```powershell
cd D:\dev-projects\Shutu-Atlas
.\scripts\install-nightly-index.ps1
Get-ScheduledTask -TaskName 'Shutu-Atlas Nightly Auto Index'
Get-ScheduledTaskInfo -TaskName 'Shutu-Atlas Nightly Auto Index'
```

The registered task runs at 02:00 local time only after 10 minutes of idle,
waits at most one hour for that idle state, uses `IgnoreNew`, does not wake the
computer, and does not replay a missed run during the day. The entry script
also rejects starts outside 02:00–04:00 and records JSONL under
`.local\logs\nightly-index\`. A manual index and the scheduled index share a
project-local OS writer lock; the safe result is `SKIPPED_RUNNING`.

Freshness in `atlas status` and the read-only `atlas_health` tool is based only
on the latest successful root-scope run. A project retry or partial run stays
visible in `last_attempt_status` and does not advance
`last_successful_index_at`. Use `--retry-project` for a daytime targeted
recovery, then let the next root changed-only run establish freshness.
