# Shutu-Atlas V2 final performance and Agent acceptance

Date: 2026-10-23
Branch: `main`
Final disposition: `PARTIAL / BLOCKED_ENV`
V2 READY: `NO`

The implementation is complete for the requested V2 lifecycle work, but the
live workspace is not a clean `READY` gate: discovery currently returns 44
eligible projects (the earlier 38-project expectation is stale), two projects
exceed the configured 20,000-file safety limit, and the daily Python
environment does not contain the official MCP SDK or Serena. No source
repository was written.

## A01-A10 gates

| Gate | Status | Evidence |
| --- | --- | --- |
| A01 source repositories remain read-only | `PASS` | `src/shutu_atlas/discovery.py:368-432` applies the shared safe-file predicate; index/gallery/MCP state is under `.local`. The run did not write any source project. |
| A02 discovery and full live indexing | `PARTIAL` | `scan-instrumented-v2.json` and run 20 discovered 44 projects. Run 20 reached terminal status for all 44: 42 complete/resumed projects and two explicit `FileLimitReached` partials. It is not described as full 44-project coverage. |
| A03 code/capability/source evidence | `PASS` | FTS5 plus bounded ripgrep, project isolation, source bounds, Git metadata, and evidence status are covered by `tests/test_index.py` and the MCP tests. |
| A04 incremental lifecycle | `PASS` | Change, delete, rename, UI preservation, stale-run recovery, stat fast path, force-hash, and checkpoint tests pass. |
| A05 Serena and official Python MCP SDK in daily env | `BLOCKED_ENV` | `.local/doctor-default-v2-final.json`: `C:\Python314\python.exe` 3.14.7, `python_mcp_sdk=false`, Serena absent. `.local/doctor-venv-v2-final.json`: `.venv` Python 3.13.15 with the same missing optional packages. The compatibility stdio server is available; official SDK/Serena remain optional evidence only. |
| A06 Gallery | `PASS` | Existing API/browser evidence remains valid; current regression suite passes the Gallery API path and the existing elevated browser evidence is retained. |
| A07 read-only MCP surface | `PASS` for the compatibility stdio surface; `BLOCKED_ENV` for official SDK | Direct MCP initialize succeeded after the index writer stopped. The server exposes query tools only; no refresh, shell, Git-write, source-write, or Gallery-write tool exists. |
| A08 local-project-reuse Skill and clients | `PASS` for real Codex CLI; `UNVERIFIED` for OpenCode | `.local/codex-e2e-20261023-retry/codex-events.jsonl` records the actual Codex CLI sequence: Skill load, `atlas_health`, `atlas_find_capability`, `atlas_search_code`, `atlas_get_source`, code generation, and pytest. OpenCode `v2.1.3` is installed, but the prior real client attempt hit `EPERM` while opening its log; no user config workaround was attempted. |
| A09 security and evidence freshness | `PASS` | Sensitive-file filtering, hidden/excluded directories, reparse points, cross-project isolation, source bounds, Git/evidence freshness, legacy UI IDs, and reuse-risk fields remain covered. |
| A10 documentation and regression closure | `PASS` with A02/A05/A08 caveats | `python -m pytest -q` => `19 passed, 5 skipped in 55.90s`; `.local/pytest-v2-final.txt` records the run. |

## Implementation evidence

| Area | Real path and lines | Result |
| --- | --- | --- |
| Stage timing/count model | `src/shutu_atlas/index/metrics.py:10-48` | Reproducible monotonic stage timings and counters. |
| Discovery/Git instrumentation | `src/shutu_atlas/discovery.py:105-330` | Discovery, stat/path checks, stack detection, Git commands, and directory traversal are recorded. |
| Shared stat-first file scan | `src/shutu_atlas/discovery.py:368-494` | One walk collects stat metadata, eligible totals, bytes, skipped counts, and limit evidence while preserving sensitive/reparse filtering. |
| Index lifecycle/checkpoints | `src/shutu_atlas/index/database.py:119-153,439-670` | Run/project checkpoints, stale-owner recovery, resume, retry, per-project commit, and terminal error state. |
| FTS row identity | `src/shutu_atlas/index/database.py:719-754` | `fts_content_rows` prevents unnecessary FTS row scans during replacement/deletion. |
| CLI controls | `src/shutu_atlas/cli.py:45-65,192` | `--changed-only`, `--force-hash`, `--resume`, `--retry-project`, and overall elapsed output. |

## Correctness and performance

Ordinary incremental mode (`changed_only_hash_mode = "stat"`) first compares
stored size and nanosecond mtime. If both match, it does not hash or read the
file and records it as unchanged. This is fast but cannot detect a same-size
content rewrite that preserves mtime. `--force-hash` hashes every eligible
file; it is the strong-validation mode and detects that case. A forced hash
run is intentionally slower.

| Workload | Old evidence | V2 evidence |
| --- | ---: | ---: |
| Deepseek no-change, 5123 files | Run 9 used the old always-hash path and ran about 26m45s across 15 projects before interruption | `benchmark-deepseek-stat-v4.json`: 1869 ms project time, 0 hashes; v5: 3243 ms, 0 hashes |
| Same workload with strong validation | Not separately measured | `benchmark-deepseek-force-hash.json`: 22636 ms project time, 5123 hashes, 20090 ms SHA-256 |
| Live discovery | Old report: 39 candidates | V2: 44 projects, 17 Git projects, 61 Git commands, 8568.498 ms in final run |
| Final live run | Earlier runs stopped after 11/17 projects | Run 20: 44/44 terminal checkpoints, 87610 files scanned, 1,077,329,312 bytes, 3287 changed/indexed files, 36634 unchanged files, 2 explicit partials, 751667.894 ms overall |

The first run 19 also provided the root cause evidence for the last-project
stall: `znexus-dashboard-demo-v3` contained `.codegraph`, `.go-cache`,
`.go-mod-cache`, `.deploy-staging*`, and `pytest-cache-files-*`; the process
reported 566,836,543,428 bytes read before interruption while that project had
no checkpoint. Those names are now excluded by the normal directory predicate.
Run 20 resumed the 43 completed checkpoints and finished the last project in
679147.256 ms.

The ordinal-16 project `eli5-business-suite` is a resumed, unchanged project
with a small stat-only checkpoint; it is not the source of the long tail. The
long running cases were content-heavy changed/new projects and the cache
directories above.

## Final live project errors

These are real terminal errors from run 20, not timeouts:

| Project | Real path | Eligible files | Scanned bytes | Skipped count | Error |
| --- | --- | ---: | ---: | ---: | --- |
| `High-End_Feature_Phones` | `D:\dev-projects\High-End_Feature_Phones` | 24622 | 356754893 | 27311 | `FileLimitReached`: 24622 eligible files exceed `max_files_per_project=20000`; 4622 over-limit files. |
| `webnovel-Agent2` | `D:\dev-projects\webnovel-Agent2` | 23067 | 118846609 | 10043 | `FileLimitReached`: 23067 eligible files exceed `max_files_per_project=20000`; 3067 over-limit files. |

For both projects the partial path performed zero content/FTS writes for the
oversized project and retained the error in `index_errors`. The remaining 42
projects have usable committed results; the final run status remains
`partial` until the file-cap decision is explicitly changed.

## Recovery and retry evidence

- Run 16 stopped after 11 project checkpoints.
- Run 17 used `resume_from_run=16`, preserved prior results, and completed the
  next project without redoing the first 11 content indexes.
- Run 19 stopped after 43 checkpoints while the last project was active.
- Run 20 used `resume_from_run=19`, restored 37 project checkpoints as
  `resumed`, rechecked them with stat metadata, and finished all 44 projects.
- Project-level retry is available through `--retry-project NAME_OR_ID`; it
  does not prune unrelated roots and does not hide project errors.

## Real Codex CLI E2E

The retry E2E target is a fresh Git repository at
`.local/codex-e2e-20261023-retry` with seed HEAD
`9a898a332fc02f4b2249be7d058d844c86f3d7c8`.

The actual command was `codex exec` with a one-shot `shutu-atlas` MCP override;
the user config was not edited. Codex read
`skills/local-project-reuse/SKILL.md`, then called:

1. `atlas_health`
2. `atlas_find_capability(query="任务重启恢复", limit=3)` (no result)
3. `atlas_find_capability(query="recover after restart", limit=3)`
4. `atlas_search_code(query="recover_after_restart", project_id="aeac851c36b9a320", limit=3)` (no exact result)
5. `atlas_get_source(project_id="aeac851c36b9a320", file_id=2329, start_line=362, end_line=374)`
6. additional bounded search/symbol checks, with Serena truthfully reported as
   `BLOCKED_ENV`.

The source evidence returned
`D:\dev-projects\English-Practice\benchmark.go:362-373`, Git HEAD
`f80ceeee2b7932ccaba962f942c00a71ee850078`, branch `main`, and only a
`PostProbeRecovery` metric field at line 366. Codex correctly classified the
old capability as `inferred/unverified`, not as a reusable implementation.
It then added only `reused_app.py` and `test_reused_app.py` in the disposable
target and ran `python -m pytest -q` => `4 passed in 0.20s`.

## Reproducible commands

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m shutu_atlas.cli --config .\atlas.toml scan --root D:\dev-projects --dry-run
python -m shutu_atlas.cli --config .\atlas.toml index --root D:\dev-projects --changed-only --resume
python -m shutu_atlas.cli --config .\atlas.toml status
python -m pytest -q
```

Use `--force-hash` when same-size/same-mtime rewrites must be detected. Use
`--retry-project NAME_OR_ID` for a bounded project retry. Do not describe a
`partial` or `interrupted` run as full coverage.

## Git handoff

The final implementation and evidence changes are committed and pushed after
the verification pass. The final commit hash is recorded here immediately
before handoff.
