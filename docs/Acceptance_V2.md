# Shutu-Atlas V2 final performance and Codex acceptance

Date: 2026-10-24

Branch: `main`
Baseline: `origin/main` was fetched successfully at the start. The final
release commit was pushed and verified on `origin/main`.

Final disposition: **V2 READY — Codex / Local Reference Library** (local
Codex gates complete).

GitHub publication: **PASS** — `origin/main` resolves to the release commit.
OpenCode: **UNVERIFIED** (separate client scope; not a Codex release gate).

This closure covers M0–M4 only. Source projects under `D:\dev-projects` were
used as read-only references. Runtime mirrors, caches, database backups,
screenshots, test-work directories, and Codex event logs remain under
`Shutu-Atlas\.local` and are not release files.

## A01–A10 gates

| Gate | Status | Evidence and result |
| --- | --- | --- |
| A01 baseline and source safety | `PASS` | `git fetch origin main` and `git status -sb` were run at M0 and before handoff. Source reference `D:\dev-projects\carbon-lens` remained clean at HEAD `4d0df686380bc2e2b802c1fd91f0327be05eb224`; no source project received files, dependencies, Serena state, or commits. |
| A02 eligible discovery and complete live index | `PASS` | `scan --root D:\dev-projects --dry-run` found 44 eligible projects. Run 23 (`.local/closure-m1-full-index.json`) completed 44/44 with `status=ok`, 87,611 eligible files, 1,077,360,336 scanned bytes, 0 partial, 0 error, and 0 interrupted projects. All 44 project file counts match the stored file rows. |
| A03 file-limit closure and evidence integrity | `PASS` | The two real over-limit projects were retried with `--changed-only --retry-project`: High-End_Feature_Phones run 21 indexed 24,622 files / 356,754,893 bytes in 5,814.400 s; webnovel-Agent2 run 22 indexed 23,067 files / 118,846,609 bytes in 5,559.902 s. The explicit cap is 30,000 in `atlas.toml` and `atlas.example.toml:16`; the five historical `FileLimitReached` rows are retained as history, not current failures. `.local/closure-m1-project-audit.json` records the per-project count/byte audit. |
| A04 discovery exclusions and incremental lifecycle | `PASS` | `.deploy-staging*` and `pytest-cache-files-*` are excluded by `src/shutu_atlas/discovery.py:43-50`; the regression is in `tests/test_index.py:30-32`. Run 23 was changed-only: 14 changed, 87,597 unchanged, 14 hashes, 0 errors. Existing checkpoint/resume, deletion/rename, FTS, UI preservation, source-bound, and stale-run tests remain green. |
| A05 official MCP SDK and Serena in the daily Codex environment | `PASS` | `.local/closure-m2-doctor.json` records Python 3.13.15, `mcp` 2.2.0, `serena-agent` 2.1.0, `uv` 0.13.5, and resolved `uv.exe`/`uvx.exe`/`serena.exe` paths. The official `mcp.Client` initialized the real stdio server, listed all 9 Atlas tools, and completed health/search/source calls. Serena returned `WriteExecutionManager` with `confidence=verified`; see `.local/closure-m2-official-mcp.json`. |
| A06 Serena isolation and source freshness | `PASS` | `src/shutu_atlas/symbols/providers.py:99-119,130-201` resolves tools beside the active Python and places `SERENA_HOME`, `UV_CACHE_DIR`, logs, and mirrors under `.local/serena-workspaces`. Serena evidence points to `D:\dev-projects\carbon-lens\src\carbon_lens\executions.py:83-787`, Git HEAD `4d0df686…`, `dirty=false`, with a Hub-owned mirror and no source `.serena` directory. |
| A07 read-only daily MCP surface and reproducible config | `PASS` | `docs/MCP_Skill_Integration.md:68-82` contains the mergeable Codex TOML entry using the integration-venv Python and `PYTHONPATH=src`. The actual one-shot Codex override did not edit user configuration. The MCP server exposes 9 query/health tools only; no refresh, shell, Git-write, source-write, or Gallery-write tool is present. |
| A08 real Codex Skill/MCP reuse E2E | `PASS` | `.local/closure-m3-codex-e2e.json` and `.local/codex-e2e-20261024/REUSE_REPORT.md` record Codex CLI 0.163.0 loading `skills/local-project-reuse/SKILL.md`, calling `atlas_health`, capability/search/symbol/source tools, and using verified Carbon Lens implementation/test evidence. It chose `adapt`, created an independent stdlib JSON checkpoint component at `checkpoint.py:14-191` with tests at `tests/test_checkpoint.py:24-64`, and the target command passed `4 passed in 0.08s`. The inferred capability at `scripts/live_acceptance.py:251` was not treated as proof; verified symbol/test evidence was used instead. |
| A09 security, build, and regression checks | `PASS` | Base `python -m pytest -q`: `20 passed, 5 skipped in 60.43s`; integration-venv pytest: `22 passed, 3 skipped in 69.83s`; `python -m compileall -q src tests`, `node --check web/app.js`, and `git diff --check` all passed. Base skips are the explicit browser opt-in, unavailable base MCP/Serena packages, Windows symlink limitation, and the corresponding MCP Skill guard; integration skips are browser opt-in, symlink limitation, and the Serena test's PATH guard. The actual warmed official MCP/Serena proof is the M2 gate above. |
| A10 documentation and Git handoff | `PASS` | This report, `docs/Operations_Windows.md`, and `docs/MCP_Skill_Integration.md` contain reproducible commands, version pins, exact paths, line-level evidence, and the OpenCode `UNVERIFIED` boundary. The final release commit is present on `origin/main` and tracked changes are clean; verify it with `git ls-remote origin refs/heads/main`. `.local` evidence and the pre-existing task file are intentionally untracked. |

## M1 index evidence

The current database audit is:

```text
eligible projects: 44
eligible/stored files: 87611 / 87611
stored bytes: 1077360336
run 23: 44/44 completed, status=ok
run 23 project statuses: ok=2, unchanged=42, partial=0, error=0, interrupted=0
current run errors: 0
historical limit errors retained: 5
```

The two large projects were audited before increasing the bounded cap. Their
file mixes and top directories are in `.local/closure-m1-project-audit.json`;
the source/UI-heavy content was not discarded as generated cache material.

## M2 official integration evidence

The actual MCP server command is:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
& .local\integration-venv\Scripts\python.exe -m shutu_atlas.cli `
  --config .\atlas.toml mcp serve --transport stdio
```

The official client listed:

```text
atlas_list_projects
atlas_find_capability
atlas_search_code
atlas_find_symbol
atlas_get_source
atlas_find_ui
atlas_get_ui_detail
atlas_suggest_reuse
atlas_health
```

`atlas_health` reported 44 projects, 87,611 files, 605,051 symbols, 254
capabilities, 5,076 UI assets, and run 23 `status=ok` with zero errors. The
source implementation/test slices returned `git_head`, `dirty=false`, and
`stale=false`.

## M3 reuse decision

Codex used Carbon Lens as the mature reference. Atlas capability indexing
classified `task_recovery` as `inferred`; Serena verified the actual
`WriteExecutionManager` symbol and the recovery test. The target implementation
was intentionally an independent adaptation rather than a copy because the
source couples execution recovery to Carbon Lens, SQLite, SSH/Beeline, MCP,
and Paramiko, while the target needed a small dependency-free checkpoint API.
The target report records the source Git HEAD, paths, lines, dependencies,
unverified license status, MCP calls, event log, target Git state, and tests.

## Release boundary

`V2 READY — Codex / Local Reference Library` applies to the Codex CLI + local
Atlas MCP/Serena environment verified above. It does not claim OpenCode
support. OpenCode remains `UNVERIFIED` because no authenticated client session
was completed and no user configuration workaround was made.

## Nightly Auto Index extension (2026-10-24)

This extension preserves the V2 READY boundary and adds only a Windows
Task-Scheduler wrapper plus status visibility. It does not claim that a
partial or targeted run is a fresh root index.

| Gate | Status | Evidence |
| --- | --- | --- |
| Code implementation | `PASS` | `scripts/nightly-index.ps1`, `scripts/install-nightly-index.ps1`, `scripts/uninstall-nightly-index.ps1`; `--changed-only --resume`, project-local writer lock, log rotation, 02:00–04:00 start guard, low-priority fallback, and accurate exit propagation are covered by `tests/test_nightly_scripts.py` and the index regression suite. |
| Actual Windows task registration | `PASS` | Live task `Shutu-Atlas Nightly Auto Index` was registered for the current user without elevation and read back from Task Scheduler: `Ready`, daily `02:00 +03:00`, `Interactive`, `Limited`, `RunOnlyIfIdle=true`, `Duration=PT10M`, `WaitTimeout=PT1H`, `IgnoreNew`, `Priority=7`, `StartWhenAvailable=false`, `WakeToRun=false`, `StopOnIdleEnd=false`. A same-task reinstall created a `.local` XML backup. |
| Automatic-run configuration | `PASS` | The installed action uses Windows PowerShell 5.1, the absolute project script, project working directory, `atlas.toml`, and the project-local integration interpreter. A controlled `Start-ScheduledTask` request stayed `Queued` while idle conditions were not satisfied and was stopped; it did not become a daytime catch-up. |
| Real changed-only scan | `PASS` | Controlled entry `nightly-index.ps1 -IgnoreTimeWindowForTest` completed run 24 with exit code 0, `status=ok`, 44/44 projects, 87,613 files scanned, 16 changed/indexed files, 87,597 unchanged files, 0 errors, database elapsed 72.814 s, wrapper elapsed 83.366 s, process priority `BelowNormal`. The bypass is not used by the registered task. |
| Freshness | `PASS` | `atlas status` and `atlas_health` read run 24 as `coverage_scope=root`, `last_successful_index_at=2026-10-24T08:25:32Z`, `freshness_level=fresh`, threshold 93,600 seconds, and a non-negative age. Targeted retry scope is persisted separately. |
| Regression | `PASS` | Required base run `python -m pytest -q`: `22 passed, 5 skipped in 46.39s`; project integration-venv run: `24 passed, 3 skipped in 58.15s` (including the official MCP health client). `python -m compileall -q src tests`, `node --check web/app.js`, and `git diff --check` passed. |
| Existing user configuration | `PASS` | `atlas.toml`, `.local\atlas.sqlite3`, historical runs, and existing source roots were retained. Only project-local `.local` runtime state and the requested tracked implementation/docs changed. |

The detailed operating procedure, uninstall command, status example, and
failure boundaries are in [`Nightly_Auto_Index.md`](Nightly_Auto_Index.md).
