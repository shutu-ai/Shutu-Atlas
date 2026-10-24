# Nightly Auto Index on Windows

Nightly Auto Index is a thin Windows Task Scheduler wrapper around the
existing V2 index lifecycle. It does not add a watcher, Windows service,
polling agent, database service, or write-capable MCP tool. The scheduled
command remains:

```text
python -m shutu_atlas.cli --config atlas.toml index --changed-only --resume
```

The wrapper uses the project-local interpreter and writes operational state
only under `D:\dev-projects\Shutu-Atlas\.local`.

## Default policy

| Setting | Value |
| --- | --- |
| Task name | `Shutu-Atlas Nightly Auto Index` |
| Trigger | Every day at 02:00 local time |
| Idle prerequisite | Windows idle for at least 10 minutes |
| Idle wait window | Up to 1 hour after the trigger |
| Missed run | Not replayed during the day (`StartWhenAvailable=false`) |
| Sleep/offline computer | Not woken; that night may be skipped |
| User session | Current user, interactive token; locked screen is allowed, logoff is not promised |
| Concurrent scheduled instance | `IgnoreNew` |
| Other Atlas writer | Project-local OS writer lock; logs `SKIPPED_RUNNING` and leaves the active writer alone |
| Priority | Windows Task Scheduler priority 7 plus process `BelowNormal` when supported |
| Idle becomes false after start | Continue at low priority; Task Scheduler does not stop the SQLite write (`StopOnIdleEnd=false`) |
| Start-time guard | The script only starts between 02:00 and 04:00 local time |

The 02:00–04:00 guard protects against a manually-started or delayed task
turning into a daytime catch-up. It is checked only at process start; an
already-started run is allowed to finish using the existing checkpoints.

## Register or remove the task

Run Windows PowerShell as the current user; administrator elevation and a
stored password are not required:

```powershell
cd D:\dev-projects\Shutu-Atlas
.\scripts\install-nightly-index.ps1
.\scripts\uninstall-nightly-index.ps1
```

Installation is idempotent. If the project-managed task already exists, its
live XML is backed up under `.local\task-scheduler-backups` before it is
updated. A same-named task without the Shutu-Atlas marker is not overwritten.
Uninstall removes only the marked task and does not delete the database, logs,
source files, historical index runs, or `atlas.toml`.

To inspect the live task and its result:

```powershell
Get-ScheduledTask -TaskName 'Shutu-Atlas Nightly Auto Index'
Get-ScheduledTaskInfo -TaskName 'Shutu-Atlas Nightly Auto Index'
Export-ScheduledTask -TaskName 'Shutu-Atlas Nightly Auto Index'
```

The installer reads the registered XML back and reports the trigger, idle
settings, `IgnoreNew`, identity, priority, working directory, and the absence
of missed-run replay/wake-to-run settings. If the ScheduledTasks module or
the current user's permissions do not allow registration, the result is
`BLOCKED_ENV`; the script does not request elevation or change power policy.

## Runtime and logs

The scheduled action runs:

```text
D:\dev-projects\Shutu-Atlas\scripts\nightly-index.ps1
```

It requires this interpreter and will fail clearly rather than using a global
Python:

```text
D:\dev-projects\Shutu-Atlas\.local\integration-venv\Scripts\python.exe
```

The wrapper sets `PYTHONPATH=...\src`, `WorkingDirectory` is the project
root, and paths are passed as separate PowerShell arguments so spaces are
safe. Daily JSONL logs are stored at:

```text
D:\dev-projects\Shutu-Atlas\.local\logs\nightly-index\YYYY-MM-DD.jsonl
```

Each invocation records start/finish or skip, the command summary, priority
result, duration, exit code, run id, project/file counters, and skip reason.
Only these task-owned JSONL files older than 30 days are rotated.

The regular entry point returns success only for a successful CLI run or a
safe skip. A partial/error CLI result keeps its non-zero exit code. A task
already running through any Atlas entry point is reported as
`SKIPPED_RUNNING`, not forced, killed, or made to race SQLite.

For a controlled verification outside the normal time window only, the
script accepts `-IgnoreTimeWindowForTest`. The registered Task Scheduler
action never passes this switch.

## Status and freshness

`atlas status` and the read-only MCP `atlas_health` surface expose the same
index status fields. The freshness timestamp is taken only from the latest
successful `coverage_scope=root` run. A targeted `--retry-project`, a
configured project subset, an interrupted run, or a partial run cannot move
the root freshness timestamp forward.

Example after the verified run 24:

```json
{
  "current_state": "ok",
  "last_attempt_status": "ok",
  "last_successful_index_at": "2026-10-24T08:25:32Z",
  "age_seconds": 5,
  "freshness_level": "fresh",
  "freshness": {
    "level": "fresh",
    "threshold_seconds": 93600,
    "coverage_scope": "root"
  },
  "last_index": {
    "run_id": 24,
    "coverage_scope": "root",
    "projects_total": 44,
    "projects_completed": 44,
    "changed_files": 16,
    "errors": 0
  }
}
```

The default stale threshold is 26 hours and can be changed with
`[limits].freshness_stale_after_hours` in the local `atlas.toml`. `unknown`
means that no qualifying root completion can be confirmed; it is not a claim
that the index is current.

## Daytime recovery and troubleshooting

The normal recovery path remains the existing V2 CLI:

```powershell
cd D:\dev-projects\Shutu-Atlas
$env:PYTHONPATH = (Resolve-Path .\src).Path
& .\.local\integration-venv\Scripts\python.exe -m shutu_atlas.cli `
  --config .\atlas.toml index --changed-only --resume
& .\.local\integration-venv\Scripts\python.exe -m shutu_atlas.cli `
  --config .\atlas.toml index --changed-only --retry-project PROJECT_NAME_OR_ID
& .\.local\integration-venv\Scripts\python.exe -m shutu_atlas.cli `
  --config .\atlas.toml status
```

Use `--retry-project` for a failed or partial project during the day. It is a
targeted run and therefore does not claim root freshness. A later root
changed-only run, normally the next night, establishes the next qualifying
freshness timestamp.

If the log says `SKIPPED_TIME_WINDOW`, no daytime catch-up occurred. If it
says `SKIPPED_RUNNING`, wait for the active manual or scheduled writer. Do not
delete `.local\atlas.sqlite3.writer.lock`, kill an index process, or remove a
SQLite journal. A process exit releases the OS lock, and `--resume` plus the
existing project checkpoints handles an interrupted run.

If the task is queued after `Start-ScheduledTask`, inspect the idle condition;
Windows may be waiting for ten minutes of idle time. This is different from a
missed-run replay and is expected to resolve only within the finite idle wait
window.

Source repositories remain read-only. Index files, logs, backups, Serena
mirrors, and test evidence stay under this project's `.local` directory.
