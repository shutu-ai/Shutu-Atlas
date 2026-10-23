# Shutu-Atlas V2 remediation and acceptance closure

Date: 2026-10-23

## Final disposition

Overall status: `PARTIAL` / `BLOCKED_ENV`. The security boundary fixes and
the read-only query, Gallery, official MCP, Serena, and Skill integration
tests pass. This is not `READY` because the real `D:\dev-projects` index run
was interrupted before all discovered projects were covered, and OpenCode
client loading remains `UNVERIFIED`.

No known P0/P1 sensitive-file or source-write boundary failure remains in the
automated test scope. The incomplete full-workspace index must not be described
as full coverage.

## A01-A10 evidence

| ID | Status | Evidence |
| --- | --- | --- |
| A01 source repositories are not rewritten | `PASS` | Serena ran against a Hub-owned mirror; `tests/test_serena_optional.py` asserts the fixture source has no `.serena`. The adapter copies only the shared allowed file set and never exposes a write call. |
| A02 discovery and full indexing | `BLOCKED_ENV` | Dry-run discovered 39 candidates under `D:\dev-projects`; configured exclusion removes `Shutu-Atlas`, leaving 38 eligible. Full `run_id=8` covered 15 projects and 8,607 files before interruption; `run_id=9` changed-only covered the same 15 projects with 0 changed files before interruption. Both had 0 project errors. DB size at the end was 343,285,760 bytes. |
| A03 code/capability/source queries | `PASS` | FTS5, restricted ripgrep, project filtering, bounded source reads, Git metadata, and static symbol fallback are covered by `tests/test_index.py` and `tests/test_symbols_mcp.py`. |
| A04 incremental lifecycle | `PASS` | `test_incremental_change_and_remove`, `test_ui_asset_identity_and_screenshot_survive_full_and_incremental_refresh`, stale-run recovery, and removed-project pruning pass. |
| A05 Serena | `PASS` (isolated) | `.local/integration-venv`: `serena-agent 2.1.0`, official `mcp 2.2.0`, `uv 0.13.5`; real Serena stdio startup, Pyright startup, `TaskStore` symbol query, mirror mapping, and source-project no-write assertion pass. The default Python environment remains truthfully `BLOCKED_ENV`. |
| A06 Gallery | `PASS` | API screenshot bytes/content type and all-project code search pass in `test_gallery_api_screenshot_preview_and_all_project_code_search`; opt-in elevated Playwright preview/detail/copy/all-project interaction passes 2 tests. |
| A07 official read-only MCP | `PASS` | Official `mcp.Client` stdio session lists Atlas tools and calls `atlas_health`; `tests/test_mcp_sdk_optional.py` passes. Atlas exposes no index refresh, shell, Git, source-write, or Gallery-write tool. |
| A08 local-project-reuse Skill / clients | `PASS` for Skill; `UNVERIFIED` for OpenCode | `test_local_project_reuse_skill_real_mcp_e2e` calls health, project/capability/code/source tools through a real MCP client, then runs a minimal feature in a fresh disposable target project. OpenCode CLI was present but its log open failed with `EPERM`; no user configuration was changed. |
| A09 security and evidence freshness | `PASS` | Sensitive credentials/key/hidden files, excluded directories, symlinks/reparse points, cross-project isolation, source bounds, manual verification expiry, legacy UI IDs, and reuse-risk fields are covered by `tests/test_index.py`. |
| A10 documentation and regression closure | `PASS` with known blockers | Base regression is `15 passed, 5 skipped`; isolated integration is `4 passed`; elevated Gallery browser E2E is `2 passed`; `node --check web/app.js` and `git diff --check` pass. Updated MCP/Skill and Windows operations docs are included. |

## Remediations and files

| Finding | Implementation evidence |
| --- | --- |
| `_rg_search()` bypassed sensitive-file rules | `src/shutu_atlas/discovery.py`: `is_sensitive`, `safe_source_path`, `allowed_source_path`, and `iter_project_files`; `src/shutu_atlas/index/database.py`: `_rg_search`, FTS/source validation. Index, ripgrep, and source reads now share one allowed-file predicate. |
| Sensitive files, hidden files, excluded dirs, and symlinks | `tests/fixtures/fixture-secrets/` and `test_allowed_file_set_is_shared_by_index_fts_rg_and_source_reads`. Reparse points are rejected before path resolution. |
| UI IDs collided across repositories | `database.py`: project-scoped `_ui_asset_id`, schema version 4, `ui_asset_aliases`, `_migrate_ui_asset_ids`, and alias resolution. `test_legacy_ui_asset_id_migration_preserves_alias_and_screenshot` and the multi-repo fixture prove compatibility and coexistence. |
| Gallery all-project query passed an empty project filter | `database.py` normalizes empty project IDs; `web/app.js` omits the filter for “all projects”; API and browser tests cover it. |
| Gallery did not display imported screenshots | `api/server.py`, `database.py` screenshot URL/detail support, `web/app.js`, and `web/styles.css` implement real thumbnails, detail preview, prompt copy, and safe fallback. |
| Full/incremental refresh lost screenshots | `database.py`: `_preserved_screenshot` plus conflict-safe UI upsert; full and changed-only regression test passes. |
| Manual `verified` status was not source-bound | `database.py`: `manual_git_head`, `manual_evidence_hash`, live evidence fingerprint, `expired` status and warning; `test_manual_verification_expires_when_evidence_changes` passes. |
| `suggest-reuse` overclaimed keyword matches | `database.py`: stack, dependency clues, evidence source, adaptation risk, target-stack match, and reuse type; CLI/MCP route through the enriched method. |
| Official integrations were unverified/incompatible | `requirements-integrations.txt` and `pyproject.toml` pin the compatible set `mcp[cli]==2.2.0`, `serena-agent==2.1.0`, `uv==0.13.5`; `symbols/providers.py` uses official MCP tools, isolated `SERENA_HOME`/`UV_CACHE_DIR`, mirror mapping, and Serena 2.1.0 result parsing. |

## Test evidence

```text
python -m pytest -q
15 passed, 5 skipped in 60.33s

python -m pytest -q tests/test_mcp_sdk_optional.py tests/test_serena_optional.py tests/test_skill_e2e.py
4 passed in 41.00s  (isolated integration environment, elevated stdio permissions)

$env:SHUTU_ATLAS_BROWSER_E2E = '1'
python -m pytest -q tests/test_gallery_frontend.py
2 passed in 9.66s  (elevated Chromium E2E)

node --check web/app.js
PASS

python -m shutu_atlas.cli doctor
SQLite FTS5: PASS; ripgrep: PASS; default Python MCP/Serena: BLOCKED_ENV;
OpenCode executable present but client invocation: UNVERIFIED.
```

Installed integration versions were checked with `pip show` and the CLI:

```text
mcp 2.2.0
serena-agent 2.1.0
uv 0.13.5
Serena 2.1.0-090dab18-dirty
```

## Index lifecycle and disk evidence

The discovery command returned 39 candidates. The configured target repository
was excluded, so the expected eligible count was 38.

| Run | Mode | Started (UTC) | Finished (UTC) | Projects seen | Files indexed | Errors | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 8 | full | 2026-10-23T13:10:41Z | 2026-10-23T15:32:09Z | 15 | 8,607 | 0 | `interrupted` |
| 9 | changed-only | 2026-10-23T15:32:29Z | 2026-10-23T15:59:14Z | 15 | 0 | 0 | `interrupted` |

The timings are approximately 2h21m28s and 26m45s. The stored database was
343,285,760 bytes at the final status check. Other project-local evidence
sizes were `.local/integration-venv` 182,005,499 bytes and `.local/test-work`
159,028,434 bytes; the project Gallery and root Serena workspace were empty at
that point. The partial index remains usable for already committed projects,
but it is not a full-workspace coverage claim.

## Remaining blockers and rerun command

1. `A02 BLOCKED_ENV`: the largest remaining discovered project(s) exceed the
   practical verification window under the current per-file SQLite/FTS
   implementation. Resume with:

   ```powershell
   $env:PYTHONPATH = (Resolve-Path 'src').Path
   python -m shutu_atlas.cli index --root D:\dev-projects --changed-only
   python -m shutu_atlas.cli status
   ```

   Accept only a returned `status=ok` run whose `projects_seen` equals the
   eligible discovered count; until then the index is partial.
2. `OpenCode UNVERIFIED`: the CLI attempted to open
   `C:\Users\swx1536744\.local\share\opencode\log\opencode.log` and received
   `EPERM`. No user-level config/log permission workaround was attempted.
3. The default Python environment intentionally remains optional-dependency
   free; official SDK/Serena evidence is available only in the isolated
   `.local/integration-venv`.

## Git handoff

Final commit: `PENDING_COMMIT`

Only `D:\dev-projects\Shutu-Atlas` and its test fixtures were changed. No
reference source project was edited, built, migrated, or used as a write
target. The final commit hash will replace `PENDING_COMMIT` after the report
and code are committed.
