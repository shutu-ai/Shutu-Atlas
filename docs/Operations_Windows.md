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

Use an explicitly approved isolated environment when verifying Serena and the
official MCP SDK:

```powershell
python -m venv .local\integration-venv
.local\integration-venv\Scripts\python.exe -m pip install -r requirements-integrations.txt
$env:PATH = "D:\dev-projects\Shutu-Atlas\.local\integration-venv\Scripts;$env:PATH"
python -m pytest -q tests/test_mcp_sdk_optional.py tests/test_serena_optional.py tests/test_skill_e2e.py
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
