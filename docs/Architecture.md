# Shutu-Atlas architecture

Shutu-Atlas is a local, read-only cross-project reference index. Source
repositories under the configured roots are scanned; SQLite/FTS5, CLI, MCP,
and Gallery state live under `.local`. Gallery defaults to `127.0.0.1`.

## Data layers

- `projects` stores the stable project ID, real path, Git HEAD/branch/dirty
  state, and discovery metadata.
- `files` stores project-relative paths, language, size, mtime, and SHA-256
  when content validation is required.
- `symbols`, `capabilities`, and `capability_evidence` map evidence back to
  real files and lines. Manual evidence has its own Git/evidence fingerprint.
- `ui_assets` and `ui_source_links` keep project-scoped UI metadata and
  screenshots.
- `fts_content` stores bounded source text for search. `fts_content_rows`
  maps stable `file_id` values to FTS row IDs.
- `index_runs` and `index_project_runs` store run-level and project-level
  progress, timing counters, errors, and resume state.

## V2 indexing lifecycle

`src/shutu_atlas/index/metrics.py:10-48` provides the monotonic stage
timer/counter contract. `src/shutu_atlas/discovery.py:221-330` records
discovery, Git status, stack detection, path checks, and directory traversal.
`scan_project_files()` at `src/shutu_atlas/discovery.py:436-494` performs one
walk and returns eligible totals, bytes, skipped directories/files, and
file-limit evidence.

The shared path predicate rejects sensitive names, non-text files, excluded
directories, and reparse points before code search or source reads. Cache and
generated directories proven to be non-source (`.codegraph`, `.go-cache`,
`.go-mod-cache`, `.deploy-staging*`, and `pytest-cache-files-*`) are excluded.

In `changed-only`/`stat` mode, size plus nanosecond mtime is the normal
incremental proof. `--force-hash` upgrades the proof to SHA-256 for every
eligible file and is intentionally slower; it is the mode required to detect a
same-size/same-mtime rewrite. The distinction is covered by
`tests/test_index.py:120-163`.

Project checkpoints are committed independently in
`src/shutu_atlas/index/database.py:467-670`. Resume validates completed
projects with stat metadata and retries only unfinished/error projects.
`fts_content_rows` is used by the FTS replacement/deletion helpers at
`src/shutu_atlas/index/database.py:719-754`, avoiding a scan for a file's FTS
row. A project over `max_files_per_project` records its actual scan and error
but does not write incomplete source/FTS content.

## Query layers

Code queries use FTS5 and bounded `rg --fixed-strings`, returning
`match_reason`, real paths, project IDs, line ranges where available, and
evidence status. Source reads require indexed `project_id + file_id` and
revalidate the current Git/evidence fingerprint. Serena is an optional symbol
provider; when unavailable the static provider reports `DEGRADED`/`BLOCKED_ENV`
and is never presented as Serena verification.

## Interfaces

- CLI: scan, index, search, capability/source lookup, status, and doctor.
- MCP: read-only stdio query tools and health; no refresh, shell, Git write,
  source write, or Gallery write tool.
- Gallery: local read-only HTTP/API surface with safe `.local/gallery` bounds.
