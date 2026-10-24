from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from typing import Any

from ..config import AtlasConfig
from ..discovery import ProjectRecord, ProjectScan, allowed_source_path, scan_project_files
from .metrics import StageMetrics, elapsed_ms, timed


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
  is_git INTEGER NOT NULL, git_head TEXT, branch TEXT, dirty INTEGER,
  git_status_hash TEXT,
  languages_json TEXT NOT NULL, frameworks_json TEXT NOT NULL, markers_json TEXT NOT NULL,
  discovery_kind TEXT NOT NULL, excluded INTEGER NOT NULL DEFAULT 0,
  exclusion_reason TEXT, indexed_at TEXT, file_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS files (
  file_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL, language TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  modified_ns INTEGER NOT NULL, sha256 TEXT NOT NULL, is_working_tree INTEGER NOT NULL DEFAULT 1,
  indexed_at TEXT NOT NULL, UNIQUE(project_id, relative_path)
);
CREATE TABLE IF NOT EXISTS symbols (
  symbol_id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  name TEXT NOT NULL, kind TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
  signature TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'static'
);
CREATE TABLE IF NOT EXISTS capabilities (
  capability_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  name TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
  manual_status TEXT, manual_label TEXT, manual_note TEXT, reviewed_at TEXT,
  manual_git_head TEXT, manual_evidence_hash TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, name)
);
CREATE TABLE IF NOT EXISTS capability_evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, capability_id INTEGER NOT NULL REFERENCES capabilities(capability_id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE, start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL, snippet TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ui_assets (
  asset_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  file_id INTEGER REFERENCES files(file_id) ON DELETE SET NULL, asset_type TEXT NOT NULL,
  name TEXT NOT NULL, search_text TEXT NOT NULL, features_json TEXT NOT NULL,
  screenshot_status TEXT NOT NULL DEFAULT 'unavailable', screenshot_path TEXT,
  confidence TEXT NOT NULL DEFAULT 'inferred', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ui_source_links (
  asset_id TEXT NOT NULL REFERENCES ui_assets(asset_id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, PRIMARY KEY(asset_id, file_id)
);
CREATE TABLE IF NOT EXISTS ui_asset_aliases (
  old_asset_id TEXT PRIMARY KEY,
  new_asset_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS index_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  mode TEXT NOT NULL, projects_seen INTEGER NOT NULL DEFAULT 0, files_indexed INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, owner_pid INTEGER,
  elapsed_ms REAL NOT NULL DEFAULT 0, projects_total INTEGER NOT NULL DEFAULT 0,
  projects_completed INTEGER NOT NULL DEFAULT 0, files_scanned INTEGER NOT NULL DEFAULT 0,
  scanned_bytes INTEGER NOT NULL DEFAULT 0, skipped_files INTEGER NOT NULL DEFAULT 0,
  changed_files INTEGER NOT NULL DEFAULT 0, unchanged_files INTEGER NOT NULL DEFAULT 0,
  stage_timings_json TEXT NOT NULL DEFAULT '{}', stage_counts_json TEXT NOT NULL DEFAULT '{}',
  hash_mode TEXT NOT NULL DEFAULT 'always', resume_from_run INTEGER,
  coverage_scope TEXT NOT NULL DEFAULT 'unknown'
);
CREATE TABLE IF NOT EXISTS index_errors (
  error_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES index_runs(run_id) ON DELETE CASCADE,
  project_id TEXT, relative_path TEXT, error_type TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS index_project_runs (
  project_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES index_runs(run_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  elapsed_ms REAL NOT NULL DEFAULT 0,
  file_count INTEGER NOT NULL DEFAULT 0,
  scanned_bytes INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  changed_count INTEGER NOT NULL DEFAULT 0,
  unchanged_count INTEGER NOT NULL DEFAULT 0,
  metadata_updates INTEGER NOT NULL DEFAULT 0,
  deleted_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  last_relative_path TEXT,
  stage_timings_json TEXT NOT NULL DEFAULT '{}',
  stage_counts_json TEXT NOT NULL DEFAULT '{}',
  error_type TEXT,
  error_message TEXT,
  UNIQUE(run_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_index_project_runs_run ON index_project_runs(run_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_content USING fts5(
  project_id UNINDEXED, file_id UNINDEXED, relative_path, language, content,
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS fts_content_rows (
  file_id INTEGER PRIMARY KEY,
  fts_rowid INTEGER NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);
"""

CAPABILITY_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("task_recovery", "异步任务持久化与重启恢复", ("resume", "recover", "restart", "checkpoint", "persisted task", "任务恢复", "重启恢复")),
    ("task_cancellation", "异步任务取消与生命周期", ("cancel", "cancellation", "abort", "任务取消", "取消任务")),
    ("task_progress", "任务进度与状态查询", ("progress", "status", "job state", "任务进度", "状态查询")),
    ("mcp_stdio", "stdio MCP", ("stdio", "model context protocol", "mcp.server.stdio", "mcp stdio")),
    ("mcp_http", "HTTP MCP", ("streamable http", "sse", "mcp http", "/mcp")),
    ("dashboard_kpi", "Dashboard KPI 卡片", ("kpi", "metric card", "stat card", "指标卡", "kpi card")),
    ("dashboard_chart", "Dashboard 图表", ("echarts", "chart", "trend", "折线图", "趋势图", "recharts", "chart.js")),
    ("dashboard_filter", "Dashboard 筛选器", ("filter", "筛选", "date range", "dropdown")),
    ("playwright_capture", "Playwright 截图采集", ("playwright", "page.screenshot", "screenshot")),
]

UI_EXTENSIONS = {".vue": "page_or_component", ".tsx": "page_or_component", ".jsx": "page_or_component", ".html": "page", ".css": "style", ".scss": "style"}
SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(slots=True)
class ProjectIndexResult:
    project_id: str
    name: str
    path: str
    status: str = "ok"
    file_count: int = 0
    scanned_bytes: int = 0
    skipped_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    metadata_updates: int = 0
    deleted_count: int = 0
    last_relative_path: str | None = None
    elapsed_ms: float = 0.0
    stage_timings: dict[str, float] | None = None
    stage_counts: dict[str, int] | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "file_count": self.file_count,
            "scanned_bytes": self.scanned_bytes,
            "skipped_count": self.skipped_count,
            "changed_count": self.changed_count,
            "unchanged_count": self.unchanged_count,
            "metadata_updates": self.metadata_updates,
            "deleted_count": self.deleted_count,
            "last_relative_path": self.last_relative_path,
            "elapsed_ms": self.elapsed_ms,
            "stage_timings_ms": self.stage_timings or {},
            "stage_counts": self.stage_counts or {},
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class IndexWriterBusy(RuntimeError):
    """Raised when another Atlas entry point owns the project-local writer lock."""


@contextmanager
def index_writer_lock(db_path: Path):
    """Coordinate every index writer without deleting stale lock files.

    The OS releases the byte/file lock when the owning process exits.  The
    marker file is deliberately retained under ``.local`` so an interrupted
    process never requires a risky lock-file deletion before recovery.
    """

    lock_path = Path(db_path).with_name(Path(db_path).name + ".writer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise IndexWriterBusy("another Atlas index writer owns the project-local lock") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise IndexWriterBusy("another Atlas index writer owns the project-local lock") from exc
        acquired = True
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ui_asset_id(relative_path: str, project_id: str | None = None) -> str:
    """Return a stable UI identity scoped to the owning project.

    The optional project argument keeps the helper source-compatible for older
    callers, while every index write supplies it to prevent cross-repository
    collisions for identical relative paths.
    """

    identity = relative_path if not project_id else f"{project_id}\0{relative_path}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def connect(db_path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_db(cfg: AtlasConfig) -> None:
    cfg.ensure_local_dirs()
    with connect(cfg.db_path) as conn:
        conn.executescript(SCHEMA)
        version_row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        try:
            schema_version = int(version_row[0]) if version_row else 1
        except (TypeError, ValueError):
            schema_version = 1
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(index_runs)")}
        for column, definition in (
            ("owner_pid", "INTEGER"),
            ("elapsed_ms", "REAL NOT NULL DEFAULT 0"),
            ("projects_total", "INTEGER NOT NULL DEFAULT 0"),
            ("projects_completed", "INTEGER NOT NULL DEFAULT 0"),
            ("files_scanned", "INTEGER NOT NULL DEFAULT 0"),
            ("scanned_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("skipped_files", "INTEGER NOT NULL DEFAULT 0"),
            ("changed_files", "INTEGER NOT NULL DEFAULT 0"),
            ("unchanged_files", "INTEGER NOT NULL DEFAULT 0"),
            ("stage_timings_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("stage_counts_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("hash_mode", "TEXT NOT NULL DEFAULT 'always'"),
            ("resume_from_run", "INTEGER"),
            ("coverage_scope", "TEXT NOT NULL DEFAULT 'unknown'"),
        ):
            if column not in run_columns:
                conn.execute(f"ALTER TABLE index_runs ADD COLUMN {column} {definition}")
        project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        if "git_status_hash" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN git_status_hash TEXT")
        capability_columns = {row[1] for row in conn.execute("PRAGMA table_info(capabilities)")}
        for column, definition in (
            ("manual_status", "TEXT"),
            ("manual_label", "TEXT"),
            ("manual_note", "TEXT"),
            ("reviewed_at", "TEXT"),
            ("manual_git_head", "TEXT"),
            ("manual_evidence_hash", "TEXT"),
        ):
            if column not in capability_columns:
                conn.execute(f"ALTER TABLE capabilities ADD COLUMN {column} {definition}")
        if schema_version < 4:
            _migrate_ui_asset_ids(conn)
        if schema_version < 6:
            _migrate_fts_rows(conn)
        conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '6')")
        conn.commit()


def _migrate_ui_asset_ids(conn: sqlite3.Connection) -> None:
    """Migrate v1-v3 path-only UI IDs to project-scoped IDs.

    The migration inserts the new parent and source-link rows before removing
    the old parent, so it works with foreign keys enabled.  Old IDs remain
    resolvable through ``ui_asset_aliases``; this preserves bookmarks and
    imported screenshot references from earlier databases.
    """

    conn.execute(
        """CREATE TABLE IF NOT EXISTS ui_asset_aliases (
            old_asset_id TEXT PRIMARY KEY,
            new_asset_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    rows = conn.execute(
        """SELECT u.*, f.relative_path
           FROM ui_assets u
           LEFT JOIN files f ON f.file_id=u.file_id
          WHERE f.relative_path IS NOT NULL"""
    ).fetchall()
    for row in rows:
        old_id = row["asset_id"]
        new_id = _ui_asset_id(row["relative_path"], row["project_id"])
        if old_id == new_id:
            continue
        if conn.execute("SELECT 1 FROM ui_assets WHERE asset_id=?", (new_id,)).fetchone():
            # The normal 24-character identity is already collision-resistant;
            # use a deterministic longer fallback if a hand-crafted legacy DB
            # contains an unexpected duplicate.
            new_id = hashlib.sha256(
                f"{row['project_id']}\0{row['relative_path']}\0{old_id}".encode("utf-8")
            ).hexdigest()[:32]
        conn.execute(
            """INSERT INTO ui_assets(
                asset_id,project_id,file_id,asset_type,name,search_text,features_json,
                screenshot_status,screenshot_path,confidence,updated_at
            ) SELECT ?,project_id,file_id,asset_type,name,search_text,features_json,
                     screenshot_status,screenshot_path,confidence,updated_at
                FROM ui_assets WHERE asset_id=?""",
            (new_id, old_id),
        )
        conn.execute(
            """INSERT INTO ui_source_links(asset_id,file_id,start_line,end_line)
               SELECT ?,file_id,start_line,end_line
                 FROM ui_source_links WHERE asset_id=?""",
            (new_id, old_id),
        )
        conn.execute("DELETE FROM ui_source_links WHERE asset_id=?", (old_id,))
        conn.execute("DELETE FROM ui_assets WHERE asset_id=?", (old_id,))
        conn.execute(
            "INSERT OR REPLACE INTO ui_asset_aliases(old_asset_id,new_asset_id,created_at) VALUES(?,?,?)",
            (old_id, new_id, utc_now()),
        )


def _migrate_fts_rows(conn: sqlite3.Connection) -> None:
    """Record FTS rowids so incremental replacement never scans the FTS body."""

    if conn.execute("SELECT 1 FROM fts_content_rows LIMIT 1").fetchone():
        return
    rows = conn.execute("SELECT rowid,file_id FROM fts_content ORDER BY rowid").fetchall()
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO fts_content_rows(file_id,fts_rowid) VALUES(?,?)",
            (row["file_id"], row["rowid"]),
        )


def _sha256(path: Path, metrics: StageMetrics | None = None) -> str:
    started = time.perf_counter_ns()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if metrics:
            metrics.add_count("hashes")
        return digest.hexdigest()
    finally:
        if metrics:
            metrics.add_elapsed("sha256", time.perf_counter_ns() - started)


def _language(path: str) -> str:
    return {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".vue": "Vue", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".go": "Go", ".rs": "Rust", ".java": "Java", ".cs": "C#", ".md": "Markdown"}.get(Path(path).suffix.lower(), "Text")


def _snippet(lines: list[str], line: int, radius: int = 1, max_chars: int = 800) -> str:
    start = max(0, line - 1 - radius)
    end = min(len(lines), line + radius + 1)
    return "".join(f"{i + 1}: {lines[i]}\n" for i in range(start, end))[:max_chars]


def extract_symbols(text: str, language: str) -> list[dict[str, Any]]:
    patterns: list[tuple[str, str]] = []
    if language == "Python":
        patterns = [("class", r"^\s*class\s+([A-Za-z_]\w*)"), ("function", r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")]
    elif language in {"JavaScript", "TypeScript", "Vue"}:
        patterns = [("class", r"^\s*class\s+([A-Za-z_$][\w$]*)"), ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), ("function", r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("), ("function", r"^\s*(?:export\s+)?(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")]
    elif language == "Go":
        patterns = [("type", r"^\s*type\s+([A-Za-z_]\w*)\s+struct"), ("function", r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")]
    elif language in {"Java", "C#", "Rust"}:
        patterns = [("class", r"^\s*(?:public\s+|private\s+|internal\s+)?class\s+([A-Za-z_]\w*)"), ("function", r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), ("function", r"^\s*(?:public\s+|private\s+|static\s+|async\s+)*[\w<>\[\],?]+\s+([A-Za-z_]\w*)\s*\(")]
    lines = text.splitlines()
    result: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        for kind, pattern in patterns:
            match = re.search(pattern, line)
            if match:
                result.append({"name": match.group(1), "kind": kind, "start_line": index, "end_line": index, "signature": line.strip()[:500], "source": "static"})
                break
    return result


def detect_capabilities(text: str, language: str = "") -> list[dict[str, Any]]:
    lines = text.splitlines()
    results: list[dict[str, Any]] = []
    for name, label, needles in CAPABILITY_RULES:
        hits = [i for i, line in enumerate(lines, 1) if any(needle.casefold() in line.casefold() for needle in needles)]
        if hits:
            # Static text is evidence of a candidate, never proof of the full runtime capability.
            # Verification belongs to an explicit integration/acceptance result, not a keyword heuristic.
            status = "inferred"
            results.append({"name": name, "label": label, "status": status, "line": hits[0], "snippet": _snippet(lines, hits[0]), "reason": f"关键词命中: {', '.join(needles[:3])}"})
    return results


def detect_ui_asset(relative_path: str, text: str, project_id: str | None = None) -> dict[str, Any] | None:
    suffix = Path(relative_path).suffix.lower()
    if suffix not in UI_EXTENSIONS:
        return None
    folded = text.casefold()
    features: list[str] = []
    for needle, label in (("kpi", "KPI"), ("echarts", "ECharts"), ("chart", "图表"), ("filter", "筛选器"), ("table", "表格"), ("dark", "深色主题"), ("--", "CSS 变量"), ("grid", "Grid 布局"), ("tailwind", "Tailwind")):
        if needle in folded:
            features.append(label)
    name = Path(relative_path).stem
    asset_id = _ui_asset_id(relative_path, project_id)
    return {"asset_id": asset_id, "asset_type": UI_EXTENSIONS[suffix], "name": name, "features": sorted(set(features)), "search_text": f"{name} {relative_path} {' '.join(features)} {text[:1500]}", "start_line": 1, "end_line": min(len(text.splitlines()), 80)}


def _query_terms(query: str) -> list[str]:
    aliases = {"任务重启恢复": ["task", "recovery", "restart", "resume"], "异步任务": ["async", "task", "job"], "深蓝 dashboard": ["dark", "dashboard", "kpi"], "趋势图": ["trend", "chart", "echarts"]}
    terms = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", query.casefold()) if len(t) > 1]
    for key, values in aliases.items():
        if key in query.casefold():
            terms.extend(values)
    return list(dict.fromkeys(terms)) or [query.strip()]


class IndexStore:
    def __init__(self, cfg: AtlasConfig):
        self.cfg = cfg
        init_db(cfg)
        self._recover_stale_runs()

    def _recover_stale_runs(self) -> None:
        """Close abandoned runs after a killed process without touching live work."""

        with connect(self.cfg.db_path) as conn:
            rows = conn.execute("SELECT run_id,owner_pid FROM index_runs WHERE status='running'").fetchall()
            changed = False
            for row in rows:
                if not _process_alive(row["owner_pid"]):
                    conn.execute(
                        "UPDATE index_runs SET finished_at=?,status='interrupted' WHERE run_id=?",
                        (utc_now(), row["run_id"]),
                    )
                    conn.execute(
                        "UPDATE index_project_runs SET finished_at=?,status='interrupted',error_type='OwnerProcessEnded',error_message='index owner process ended' WHERE run_id=? AND status='running'",
                        (utc_now(), row["run_id"]),
                    )
                    changed = True
            if changed:
                conn.commit()

    def _upsert_project(self, conn: sqlite3.Connection, project: ProjectRecord) -> None:
        conn.execute(
            """INSERT INTO projects(project_id,name,path,is_git,git_head,branch,dirty,git_status_hash,languages_json,frameworks_json,markers_json,discovery_kind,excluded,exclusion_reason,indexed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET name=excluded.name,path=excluded.path,is_git=excluded.is_git,git_head=excluded.git_head,branch=excluded.branch,dirty=excluded.dirty,git_status_hash=excluded.git_status_hash,languages_json=excluded.languages_json,frameworks_json=excluded.frameworks_json,markers_json=excluded.markers_json,discovery_kind=excluded.discovery_kind,excluded=excluded.excluded,exclusion_reason=excluded.exclusion_reason,indexed_at=excluded.indexed_at""",
            (project.project_id, project.name, project.path, int(project.is_git), project.git_head, project.branch, None if project.dirty is None else int(project.dirty), project.git_status_hash, json.dumps(project.languages), json.dumps(project.frameworks), json.dumps(project.markers), project.discovery_kind, int(project.excluded), project.exclusion_reason, utc_now()),
        )

    def index(
        self,
        projects: Iterable[ProjectRecord],
        changed_only: bool = False,
        force_hash: bool = False,
        resume: bool = False,
        retry_projects: Iterable[str] | None = None,
        discovery_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one index under the shared project-local writer lock.

        Task Scheduler's ``IgnoreNew`` setting only coordinates instances of
        the scheduled task.  This guard also coordinates manual CLI and other
        Atlas entry points before they can write SQLite or FTS content.
        """

        try:
            with index_writer_lock(self.cfg.db_path):
                return self._index_unlocked(
                    projects,
                    changed_only=changed_only,
                    force_hash=force_hash,
                    resume=resume,
                    retry_projects=retry_projects,
                    discovery_report=discovery_report,
                )
        except IndexWriterBusy:
            hash_mode = "force-hash" if force_hash and changed_only else ("stat" if changed_only else "always")
            return {
                "run_id": None,
                "mode": "changed-only" if changed_only else "full",
                "hash_mode": hash_mode,
                "resume_from_run": None,
                "coverage_scope": "skipped",
                "projects_total": 0,
                "projects_seen": 0,
                "projects_completed": 0,
                "files_indexed": 0,
                "files_scanned": 0,
                "scanned_bytes": 0,
                "skipped_files": 0,
                "changed_files": 0,
                "unchanged_files": 0,
                "errors": 0,
                "status": "skipped_running",
                "skip_reason": "another Atlas index writer owns the project-local lock",
                "elapsed_ms": 0.0,
                "stage_timings_ms": {},
                "stage_counts": {},
                "projects": [],
            }

    def _index_unlocked(
        self,
        projects: Iterable[ProjectRecord],
        changed_only: bool = False,
        force_hash: bool = False,
        resume: bool = False,
        retry_projects: Iterable[str] | None = None,
        discovery_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.cfg.ensure_local_dirs()
        started = time.perf_counter_ns()
        project_list = list(projects)
        eligible = [project for project in project_list if not project.excluded]
        retry_set = {str(value) for value in (retry_projects or []) if str(value)}
        retry_only = bool(retry_set)
        target_projects = [
            project for project in eligible
            if not retry_set or project.name in retry_set or project.project_id in retry_set
        ]
        force_hash = bool(force_hash and changed_only)
        hash_mode = "force-hash" if force_hash else ("stat" if changed_only else "always")
        mode = "changed-only" if changed_only else "full"
        coverage_scope = "targeted-retry" if retry_only else ("configured-projects" if self.cfg.include_projects else "root")
        run_metrics = StageMetrics()
        project_results: list[ProjectIndexResult] = []

        with connect(self.cfg.db_path) as conn:
            resume_from_run: int | None = None
            resume_checkpoints: dict[str, sqlite3.Row] = {}
            if resume:
                previous_run = conn.execute(
                    "SELECT * FROM index_runs WHERE status='interrupted' AND mode=? ORDER BY run_id DESC LIMIT 1",
                    (mode,),
                ).fetchone()
                if previous_run:
                    previous_hash_mode = previous_run["hash_mode"] if "hash_mode" in previous_run.keys() else None
                    if previous_hash_mode in {None, hash_mode, "always"}:
                        resume_from_run = int(previous_run["run_id"])
                        resume_checkpoints = {
                            row["project_id"]: row
                            for row in conn.execute(
                                "SELECT * FROM index_project_runs WHERE run_id=? AND status IN ('ok','unchanged','resumed')",
                                (resume_from_run,),
                            ).fetchall()
                        }
            cur = conn.execute(
                """INSERT INTO index_runs(
                    started_at,mode,status,owner_pid,projects_total,hash_mode,resume_from_run,coverage_scope,
                    stage_timings_json,stage_counts_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    utc_now(), mode, "running", os.getpid(), len(target_projects), hash_mode,
                    resume_from_run, coverage_scope, "{}", "{}",
                ),
            )
            run_id = int(cur.lastrowid)
            conn.commit()
            counts: dict[str, int] = {
                "projects_seen": 0,
                "projects_completed": 0,
                "files_indexed": 0,
                "files_scanned": 0,
                "scanned_bytes": 0,
                "skipped_files": 0,
                "changed_files": 0,
                "unchanged_files": 0,
                "errors": 0,
            }
            if discovery_report:
                for name, value in discovery_report.get("operation_counts", {}).items():
                    run_metrics.add_count(f"discovery.{name}", int(value))

            def update_run(status: str = "running") -> None:
                stage_timings = dict(run_metrics.timings_ms())
                if discovery_report:
                    discovery_timings = discovery_report.get("timings_ms", {})
                    for name, value in discovery_timings.items():
                        stage_timings[f"discovery.{name}"] = value
                stage_timings["total"] = elapsed_ms(started)
                conn.execute(
                    """UPDATE index_runs SET finished_at=?,elapsed_ms=?,projects_seen=?,projects_completed=?,
                        files_indexed=?,files_scanned=?,scanned_bytes=?,skipped_files=?,changed_files=?,
                        unchanged_files=?,errors=?,status=?,stage_timings_json=?,stage_counts_json=?
                        WHERE run_id=?""",
                    (
                        utc_now() if status != "running" else None, stage_timings["total"],
                        counts["projects_seen"], counts["projects_completed"], counts["files_indexed"],
                        counts["files_scanned"], counts["scanned_bytes"], counts["skipped_files"],
                        counts["changed_files"], counts["unchanged_files"], counts["errors"], status,
                        json.dumps(stage_timings, ensure_ascii=False),
                        json.dumps(run_metrics.counts, ensure_ascii=False), run_id,
                    ),
                )

            for ordinal, project in enumerate(target_projects, 1):
                counts["projects_seen"] += 1
                project_started = time.perf_counter_ns()
                checkpoint = resume_checkpoints.get(project.project_id)
                result = ProjectIndexResult(project.project_id, project.name, project.path)
                conn.execute(
                    """INSERT INTO index_project_runs(
                        run_id,project_id,ordinal,name,path,started_at,status
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (run_id, project.project_id, ordinal, project.name, project.path, utc_now(), "running"),
                )
                conn.commit()
                try:
                    scan: ProjectScan | None = None
                    if checkpoint and not force_hash:
                        scan = scan_project_files(project, self.cfg)
                        if self._scan_matches_existing(conn, project.project_id, scan):
                            with timed(run_metrics, "sqlite_write"):
                                self._upsert_project(conn, project)
                                conn.execute(
                                    "UPDATE projects SET file_count=(SELECT count(*) FROM files WHERE project_id=?) WHERE project_id=?",
                                    (project.project_id, project.project_id),
                                )
                            result = self._resumed_result(project, scan, project_started)
                        else:
                            result = self._index_project(
                                conn, project, changed_only=True, force_hash=False, scan=scan,
                            )
                    else:
                        result = self._index_project(
                            conn, project, changed_only=changed_only, force_hash=force_hash, scan=None,
                        )
                    conn.commit()
                    for name, value in (result.stage_timings or {}).items():
                        run_metrics.add_elapsed(name, int(float(value) * 1_000_000))
                    for name, value in (result.stage_counts or {}).items():
                        run_metrics.add_count(name, int(value))
                    if result.status == "partial":
                        counts["errors"] += 1
                        conn.execute(
                            "INSERT INTO index_errors(run_id,project_id,relative_path,error_type,message,created_at) VALUES(?,?,?,?,?,?)",
                            (run_id, project.project_id, result.last_relative_path, result.error_type or "PartialProject", result.error_message or "project scan was truncated", utc_now()),
                        )
                    counts["files_indexed"] += result.changed_count
                    counts["files_scanned"] += result.file_count
                    counts["scanned_bytes"] += result.scanned_bytes
                    counts["skipped_files"] += result.skipped_count
                    counts["changed_files"] += result.changed_count
                    counts["unchanged_files"] += result.unchanged_count
                    counts["projects_completed"] += 1
                except KeyboardInterrupt:
                    conn.rollback()
                    result.status = "interrupted"
                    result.elapsed_ms = elapsed_ms(project_started)
                    self._finish_project_run(conn, run_id, result)
                    update_run("interrupted")
                    conn.commit()
                    raise
                except Exception as exc:  # keep other projects independently indexable
                    conn.rollback()
                    counts["errors"] += 1
                    result.status = "error"
                    result.error_type = type(exc).__name__
                    result.error_message = str(exc)[:1000]
                    result.elapsed_ms = elapsed_ms(project_started)
                    conn.execute(
                        "INSERT INTO index_errors(run_id,project_id,relative_path,error_type,message,created_at) VALUES(?,?,?,?,?,?)",
                        (run_id, project.project_id, None, type(exc).__name__, str(exc)[:1000], utc_now()),
                    )
                self._finish_project_run(conn, run_id, result)
                project_results.append(result)
                update_run("running")
                conn.commit()

            # A root-wide reconciliation is only safe after every target was
            # visited successfully.  Targeted retries never prune other data.
            if not self.cfg.include_projects and not retry_only and counts["errors"] == 0:
                ids = [project.project_id for project in eligible]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    orphan_rows = conn.execute(
                        f"SELECT project_id FROM projects WHERE project_id NOT IN ({placeholders})", ids,
                    ).fetchall()
                    for orphan in orphan_rows:
                        conn.execute("DELETE FROM fts_content WHERE project_id=?", (orphan["project_id"],))
                    conn.execute(f"DELETE FROM projects WHERE project_id NOT IN ({placeholders})", ids)
                else:
                    conn.execute("DELETE FROM fts_content")
                    conn.execute("DELETE FROM projects")
                conn.execute("DELETE FROM fts_content WHERE project_id NOT IN (SELECT project_id FROM projects)")
                conn.execute("DELETE FROM fts_content_rows WHERE file_id NOT IN (SELECT file_id FROM files)")
                conn.commit()
            final_status = "ok" if counts["errors"] == 0 and counts["projects_completed"] == len(target_projects) else "partial"
            update_run(final_status)
            conn.commit()
            result = {
                "run_id": run_id,
                "mode": mode,
                "hash_mode": hash_mode,
                "resume_from_run": resume_from_run,
                "coverage_scope": coverage_scope,
                "projects_total": len(target_projects),
                **counts,
                "status": final_status,
                "elapsed_ms": elapsed_ms(started),
                "stage_timings_ms": json.loads(conn.execute("SELECT stage_timings_json FROM index_runs WHERE run_id=?", (run_id,)).fetchone()[0]),
                "stage_counts": run_metrics.counts,
                "projects": [item.to_dict() for item in project_results],
            }
            return result

    def _scan_matches_existing(self, conn: sqlite3.Connection, project_id: str, scan: ProjectScan) -> bool:
        if scan.truncated:
            return False
        rows = conn.execute(
            "SELECT relative_path,size_bytes,modified_ns FROM files WHERE project_id=?",
            (project_id,),
        ).fetchall()
        if len(rows) != len(scan.files):
            return False
        old = {row["relative_path"]: row for row in rows}
        for item in scan.files:
            previous = old.get(item.relative)
            if not previous or previous["size_bytes"] != item.stat_result.st_size or previous["modified_ns"] != item.stat_result.st_mtime_ns:
                return False
        return True

    def _resumed_result(self, project: ProjectRecord, scan: ProjectScan, started_ns: int) -> ProjectIndexResult:
        result = ProjectIndexResult(
            project_id=project.project_id,
            name=project.name,
            path=project.path,
            status="resumed",
            file_count=scan.eligible_total or len(scan.files),
            scanned_bytes=scan.scanned_bytes,
            skipped_count=scan.skipped_count,
            unchanged_count=len(scan.files),
            elapsed_ms=elapsed_ms(started_ns),
            stage_timings=scan.metrics.timings_ms(),
            stage_counts=dict(scan.metrics.counts),
        )
        return result

    def _finish_project_run(self, conn: sqlite3.Connection, run_id: int, result: ProjectIndexResult) -> None:
        conn.execute(
            """UPDATE index_project_runs SET finished_at=?,elapsed_ms=?,file_count=?,scanned_bytes=?,
                skipped_count=?,changed_count=?,unchanged_count=?,metadata_updates=?,deleted_count=?,
                status=?,last_relative_path=?,stage_timings_json=?,stage_counts_json=?,error_type=?,error_message=?
                WHERE run_id=? AND project_id=?""",
            (
                utc_now(), result.elapsed_ms, result.file_count, result.scanned_bytes, result.skipped_count,
                result.changed_count, result.unchanged_count, result.metadata_updates, result.deleted_count,
                result.status, result.last_relative_path,
                json.dumps(result.stage_timings or {}, ensure_ascii=False),
                json.dumps(result.stage_counts or {}, ensure_ascii=False),
                result.error_type, result.error_message, run_id, result.project_id,
            ),
        )

    def _fts_rowid(self, conn: sqlite3.Connection, file_id: int) -> int:
        row = conn.execute("SELECT fts_rowid FROM fts_content_rows WHERE file_id=?", (file_id,)).fetchone()
        if row:
            return int(row[0])
        candidate = int(file_id)
        if conn.execute("SELECT 1 FROM fts_content WHERE rowid=?", (candidate,)).fetchone():
            candidate = int(conn.execute("SELECT COALESCE(MAX(rowid),0)+1 FROM fts_content").fetchone()[0])
        conn.execute("INSERT INTO fts_content_rows(file_id,fts_rowid) VALUES(?,?)", (file_id, candidate))
        return candidate

    def _replace_fts_row(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        file_id: int,
        relative: str,
        language: str,
        text: str,
    ) -> None:
        rowid = self._fts_rowid(conn, file_id)
        conn.execute("DELETE FROM fts_content WHERE rowid=?", (rowid,))
        conn.execute(
            "INSERT INTO fts_content(rowid,project_id,file_id,relative_path,language,content) VALUES(?,?,?,?,?,?)",
            (rowid, project_id, file_id, relative, language, text),
        )

    def _delete_fts_row(self, conn: sqlite3.Connection, file_id: int) -> None:
        row = conn.execute("SELECT fts_rowid FROM fts_content_rows WHERE file_id=?", (file_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM fts_content WHERE rowid=?", (int(row[0]),))
            conn.execute("DELETE FROM fts_content_rows WHERE file_id=?", (file_id,))
        else:
            # Compatibility with a hand-created/older database that has no
            # migration row yet.  This path is only used once per such file.
            conn.execute("DELETE FROM fts_content WHERE file_id=?", (file_id,))

    def _index_project(
        self,
        conn: sqlite3.Connection,
        project: ProjectRecord,
        changed_only: bool,
        force_hash: bool = False,
        scan: ProjectScan | None = None,
    ) -> ProjectIndexResult:
        started = time.perf_counter_ns()
        metrics = StageMetrics()
        now = utc_now()
        scan = scan or scan_project_files(project, self.cfg)
        metrics.merge(scan.metrics)
        if scan.truncated:
            with timed(metrics, "sqlite_write"):
                self._upsert_project(conn, project)
            return ProjectIndexResult(
                project_id=project.project_id,
                name=project.name,
                path=project.path,
                status="partial",
                file_count=scan.eligible_total,
                scanned_bytes=scan.scanned_bytes,
                skipped_count=scan.skipped_count,
                elapsed_ms=elapsed_ms(started),
                stage_timings=metrics.timings_ms(),
                stage_counts=dict(metrics.counts),
                error_type="FileLimitReached",
                error_message=(
                    f"{scan.eligible_total} eligible files exceed max_files_per_project="
                    f"{self.cfg.limits.max_files_per_project}"
                ),
            )
        with timed(metrics, "sqlite_write"):
            self._upsert_project(conn, project)
        old = {row["relative_path"]: dict(row) for row in conn.execute("SELECT * FROM files WHERE project_id=?", (project.project_id,))}
        old_assets = {
            row["file_id"]: dict(row)
            for row in conn.execute("SELECT * FROM ui_assets WHERE project_id=?", (project.project_id,))
        }
        seen: set[str] = set()
        changed = 0
        unchanged = 0
        metadata_updates = 0
        last_relative: str | None = None

        for item in scan.files:
            path = item.path
            relative = item.relative
            stat_result = item.stat_result
            seen.add(relative)
            last_relative = relative
            previous = old.get(relative)
            stat_same = bool(
                previous
                and previous["size_bytes"] == stat_result.st_size
                and previous["modified_ns"] == stat_result.st_mtime_ns
            )
            if changed_only and stat_same and not force_hash:
                unchanged += 1
                continue

            digest = _sha256(path, metrics)
            if changed_only and previous and digest == previous["sha256"]:
                if not stat_same:
                    with timed(metrics, "sqlite_write"):
                        conn.execute(
                            "UPDATE files SET size_bytes=?,modified_ns=?,sha256=?,indexed_at=? WHERE file_id=?",
                            (stat_result.st_size, stat_result.st_mtime_ns, digest, now, previous["file_id"]),
                        )
                    metadata_updates += 1
                unchanged += 1
                continue

            with timed(metrics, "read_source"):
                text = path.read_text(encoding="utf-8", errors="replace")[: self.cfg.limits.max_chars * 64]
            language = _language(relative)
            with timed(metrics, "symbol_detection"):
                symbols = extract_symbols(text, language)
            with timed(metrics, "capability_detection"):
                capabilities = detect_capabilities(text, language)

            with timed(metrics, "sqlite_write"):
                if previous:
                    conn.execute(
                        "UPDATE files SET language=?,size_bytes=?,modified_ns=?,sha256=?,is_working_tree=1,indexed_at=? WHERE file_id=?",
                        (language, stat_result.st_size, stat_result.st_mtime_ns, digest, now, previous["file_id"]),
                    )
                    file_id = int(previous["file_id"])
                else:
                    cursor = conn.execute(
                        "INSERT INTO files(project_id,relative_path,language,size_bytes,modified_ns,sha256,is_working_tree,indexed_at) VALUES(?,?,?,?,?,?,1,?)",
                        (project.project_id, relative, language, stat_result.st_size, stat_result.st_mtime_ns, digest, now),
                    )
                    file_id = int(cursor.lastrowid)
                conn.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
                conn.executemany(
                    "INSERT INTO symbols(file_id,name,kind,start_line,end_line,signature,source) VALUES(?,?,?,?,?,?,?)",
                    [(file_id, s["name"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["source"]) for s in symbols],
                )
                conn.execute("DELETE FROM capability_evidence WHERE file_id=?", (file_id,))
                for capability in capabilities:
                    conn.execute(
                        "INSERT INTO capabilities(project_id,name,label,status,updated_at) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(project_id,name) DO UPDATE SET "
                        "label=CASE WHEN capabilities.manual_label IS NULL THEN excluded.label ELSE capabilities.manual_label END, "
                        "status=CASE WHEN capabilities.manual_status IS NULL THEN excluded.status ELSE capabilities.manual_status END, "
                        "updated_at=excluded.updated_at",
                        (project.project_id, capability["name"], capability["label"], capability["status"], now),
                    )
                    cap_id = conn.execute(
                        "SELECT capability_id FROM capabilities WHERE project_id=? AND name=?",
                        (project.project_id, capability["name"]),
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT INTO capability_evidence(capability_id,file_id,start_line,end_line,snippet,reason) VALUES(?,?,?,?,?,?)",
                        (cap_id, file_id, capability["line"], capability["line"], capability["snippet"], capability["reason"]),
                    )

            with timed(metrics, "fts_write"):
                self._replace_fts_row(conn, project.project_id, file_id, relative, language, text)

            previous_asset = old_assets.get(file_id)
            if previous_asset or Path(relative).suffix.lower() in UI_EXTENSIONS:
                with timed(metrics, "sqlite_write"):
                    conn.execute("DELETE FROM ui_source_links WHERE file_id=?", (file_id,))
                    conn.execute("DELETE FROM ui_assets WHERE file_id=?", (file_id,))
                    asset = detect_ui_asset(relative, text, project.project_id)
                    if asset:
                        screenshot_status, screenshot_path = self._preserved_screenshot(previous_asset)
                        conn.execute(
                            """INSERT INTO ui_assets(
                                asset_id,project_id,file_id,asset_type,name,search_text,features_json,
                                screenshot_status,screenshot_path,confidence,updated_at
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(asset_id) DO UPDATE SET
                                project_id=excluded.project_id,file_id=excluded.file_id,
                                asset_type=excluded.asset_type,name=excluded.name,
                                search_text=excluded.search_text,features_json=excluded.features_json,
                                screenshot_status=excluded.screenshot_status,
                                screenshot_path=excluded.screenshot_path,
                                confidence=excluded.confidence,updated_at=excluded.updated_at""",
                            (
                                asset["asset_id"], project.project_id, file_id, asset["asset_type"], asset["name"],
                                asset["search_text"], json.dumps(asset["features"], ensure_ascii=False),
                                screenshot_status, screenshot_path, "inferred", now,
                            ),
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO ui_source_links(asset_id,file_id,start_line,end_line) VALUES(?,?,?,?)",
                            (asset["asset_id"], file_id, asset["start_line"], asset["end_line"]),
                        )
            changed += 1

        deleted = 0
        with timed(metrics, "sqlite_write"):
            for relative, row in old.items():
                if relative in seen:
                    continue
                file_id = row["file_id"]
                conn.execute("DELETE FROM ui_source_links WHERE file_id=?", (file_id,))
                conn.execute("DELETE FROM ui_assets WHERE file_id=?", (file_id,))
                conn.execute("DELETE FROM files WHERE file_id=?", (file_id,))
                self._delete_fts_row(conn, file_id)
                deleted += 1
            conn.execute(
                "DELETE FROM capabilities WHERE project_id=? AND capability_id NOT IN "
                "(SELECT DISTINCT c.capability_id FROM capabilities c JOIN capability_evidence e ON e.capability_id=c.capability_id WHERE c.project_id=?)",
                (project.project_id, project.project_id),
            )
            conn.execute(
                "UPDATE projects SET file_count=(SELECT count(*) FROM files WHERE project_id=?) WHERE project_id=?",
                (project.project_id, project.project_id),
            )
        status = "partial" if scan.truncated else ("unchanged" if changed == 0 and metadata_updates == 0 and deleted == 0 else "ok")
        return ProjectIndexResult(
            project_id=project.project_id,
            name=project.name,
            path=project.path,
            status=status,
            file_count=scan.eligible_total or len(scan.files),
            scanned_bytes=scan.scanned_bytes,
            skipped_count=scan.skipped_count,
            changed_count=changed,
            unchanged_count=unchanged,
            metadata_updates=metadata_updates,
            deleted_count=deleted,
            last_relative_path=last_relative,
            elapsed_ms=elapsed_ms(started),
            stage_timings=metrics.timings_ms(),
            stage_counts=dict(metrics.counts),
            error_type="FileLimitReached" if scan.truncated else None,
            error_message="max_files_per_project reached; project index is incomplete" if scan.truncated else None,
        )

    def _preserved_screenshot(self, previous_asset: dict[str, Any] | None) -> tuple[str, str | None]:
        """Keep a user-imported screenshot when a UI source file is reindexed."""

        if not previous_asset or previous_asset.get("screenshot_status") != "available":
            return "unavailable", None
        screenshot_path = previous_asset.get("screenshot_path")
        if not screenshot_path:
            return "unavailable", None
        try:
            gallery_root = self.cfg.gallery_dir.resolve()
            target = (self.cfg.project_root / screenshot_path).resolve()
            if gallery_root not in target.parents or not target.is_file():
                return "unavailable", None
            return "available", screenshot_path
        except (OSError, ValueError):
            return "unavailable", None

    def list_projects(self, filter_text: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute("SELECT * FROM projects WHERE excluded=0 AND (? IS NULL OR name LIKE ? OR path LIKE ?) ORDER BY name LIMIT ?", (filter_text, f"%{filter_text}%" if filter_text else None, f"%{filter_text}%" if filter_text else None, limit)).fetchall()
        return [self._project_dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Return one indexed project for isolated symbol-provider work."""

        with connect(self.cfg.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id=? AND excluded=0",
                (project_id,),
            ).fetchone()
        return self._project_dict(row) if row else None

    @staticmethod
    def _project_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for key in ("languages_json", "frameworks_json", "markers_json"):
            d[key.removesuffix("_json")] = json.loads(d.pop(key))
        d["dirty"] = None if d["dirty"] is None else bool(d["dirty"])
        d["is_git"] = bool(d["is_git"])
        return d

    def search_code(self, query: str, limit: int = 10, project_id: str | None = None, language: str | None = None) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        terms = _query_terms(query)
        fts_query = " OR ".join('"' + t.replace('"', ' ') + '"' for t in terms)
        results: list[dict[str, Any]] = []
        with connect(self.cfg.db_path, readonly=True) as conn:
            sql = "SELECT f.project_id,f.file_id,f.relative_path,f.language,p.path,p.git_head,p.branch,p.dirty,s.highlight FROM fts_content f JOIN (SELECT project_id,file_id,relative_path,language,content,highlight(fts_content,4,'[HIGHLIGHT]','[/HIGHLIGHT]') AS highlight FROM fts_content WHERE fts_content MATCH ?) s ON s.file_id=f.file_id JOIN projects p ON p.project_id=f.project_id WHERE p.excluded=0 AND (? IS NULL OR f.project_id=?) AND (? IS NULL OR f.language=?) LIMIT ?"
            try:
                rows = conn.execute(sql, (fts_query, project_id, project_id, language, language, limit)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                try:
                    allowed_source_path(Path(row["path"]), row["relative_path"], self.cfg)
                except (OSError, ValueError):
                    continue
                results.append({"project_id": row["project_id"], "file_id": row["file_id"], "relative_path": row["relative_path"], "language": row["language"], "git_head": row["git_head"], "branch": row["branch"], "dirty": None if row["dirty"] is None else bool(row["dirty"]), "snippet": row["highlight"][: self.cfg.limits.max_chars], "match_reason": "fts", "evidence": "SQLite FTS5 BM25 candidate"})
        for item in self._rg_search(query, limit, project_id, language):
            if not any(r["project_id"] == item["project_id"] and r["relative_path"] == item["relative_path"] and r.get("line") == item.get("line") for r in results):
                results.append(item)
            if len(results) >= limit:
                break
        return {"status": "ok", "query": query, "terms": terms, "results": results[:limit], "warnings": [] if shutil.which("rg") else ["rg_unavailable"]}

    def _rg_search(self, query: str, limit: int, project_id: str | None, language: str | None) -> list[dict[str, Any]]:
        if not shutil.which("rg"):
            return []
        project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT p.project_id,p.path,p.git_head,p.branch,p.dirty,f.file_id,f.relative_path
                   FROM projects p JOIN files f ON f.project_id=p.project_id
                  WHERE p.excluded=0 AND (? IS NULL OR p.project_id=?)
                  ORDER BY p.project_id,f.relative_path""",
                (project_id, project_id),
            ).fetchall()
        results: list[dict[str, Any]] = []
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["project_id"], []).append(row)
        for project_rows in grouped.values():
            row = project_rows[0]
            root = Path(row["path"]).resolve()
            allowed: dict[str, int] = {}
            for candidate in project_rows:
                rel = Path(candidate["relative_path"]).as_posix()
                try:
                    allowed_source_path(root, rel, self.cfg)
                except (OSError, ValueError):
                    continue
                allowed[rel] = int(candidate["file_id"])
            if not allowed:
                continue
            # Pass only indexed/allowed relative paths to rg.  This avoids
            # relying on a partially overlapping glob blacklist and prevents
            # ignored, hidden, excluded or linked files from being searched.
            allowed_paths = list(allowed)
            for offset in range(0, len(allowed_paths), 128):
                chunk = allowed_paths[offset:offset + 128]
                try:
                    proc = subprocess.run(
                        [
                            "rg", "--line-number", "--no-heading", "--color", "never",
                            "--fixed-strings", "--max-count", "3", "--no-ignore", "--",
                            query, *chunk,
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.cfg.limits.command_timeout_seconds,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                for raw in proc.stdout.splitlines():
                    match = re.match(r"^(.*):(\d+):(.*)$", raw)
                    if not match:
                        continue
                    path, line, text = match.groups()
                    rel = Path(path).as_posix()
                    if rel.startswith("./"):
                        rel = rel[2:]
                    if rel not in allowed:
                        continue
                    if language and _language(rel) != language:
                        continue
                    results.append({"project_id": row["project_id"], "file_id": allowed[rel], "relative_path": rel, "language": _language(rel), "git_head": row["git_head"], "branch": row["branch"], "dirty": None if row["dirty"] is None else bool(row["dirty"]), "line": int(line), "snippet": text[: self.cfg.limits.max_chars], "match_reason": "regex", "evidence": "ripgrep fixed-string match"})
                    if len(results) >= limit:
                        return results
        return results

    def find_capability(self, query: str, limit: int = 10, project_filter: str | None = None) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        terms = _query_terms(query)
        with connect(self.cfg.db_path, readonly=True) as conn:
            term_conditions = ["(COALESCE(c.manual_label,c.label) LIKE ? OR c.name LIKE ? OR e.snippet LIKE ?)"] * len(terms)
            conditions = ["(" + " OR ".join(term_conditions) + ")"]
            params: list[Any] = []
            for term in terms:
                params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
            if project_filter:
                conditions.append("(p.name LIKE ? OR p.project_id=?)")
                params.extend([f"%{project_filter}%", project_filter])
            rows = conn.execute(
                f"""SELECT c.capability_id,c.name,
                           COALESCE(c.manual_label,c.label) AS label,
                           c.status AS inferred_status,c.manual_status,c.manual_note,c.reviewed_at,
                           c.manual_git_head,c.manual_evidence_hash,
                           p.project_id,p.name AS project_name,p.path,p.git_head,p.branch,p.dirty,
                           p.languages_json,p.frameworks_json,p.markers_json,
                           e.file_id,f.language,f.relative_path,e.start_line,e.end_line,e.snippet,e.reason
                      FROM capabilities c
                      JOIN projects p ON p.project_id=c.project_id
                      JOIN capability_evidence e ON e.capability_id=c.capability_id
                      JOIN files f ON f.file_id=e.file_id
                     WHERE p.excluded=0 AND {' AND '.join(conditions)}
                     ORDER BY CASE COALESCE(c.manual_status,c.status)
                                WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 ELSE 2 END,
                              CASE WHEN f.language IN ('Markdown','JSON','TOML','Text') THEN 1 ELSE 0 END,
                              p.name LIMIT ?""",
                (*params, limit),
            ).fetchall()
        results = [dict(row) for row in rows]
        fingerprint_cache: dict[int, str] = {}
        warnings: list[str] = []
        for item in results:
            item["dirty"] = None if item["dirty"] is None else bool(item["dirty"])
            item["languages"] = json.loads(item.pop("languages_json"))
            item["frameworks"] = json.loads(item.pop("frameworks_json"))
            item["markers"] = json.loads(item.pop("markers_json"))
            capability_id = int(item["capability_id"])
            if capability_id not in fingerprint_cache:
                with connect(self.cfg.db_path, readonly=True) as live_conn:
                    fingerprint_cache[capability_id] = self._capability_evidence_fingerprint(live_conn, capability_id)
            current_hash = fingerprint_cache[capability_id]
            manual_status = item.get("manual_status")
            expired = bool(
                manual_status == "verified"
                and (
                    not item.get("manual_evidence_hash")
                    or item.get("manual_evidence_hash") != current_hash
                    or (
                        item.get("git_head") is not None
                        and item.get("manual_git_head") != item.get("git_head")
                    )
                )
            )
            item["status"] = "expired" if expired else (manual_status or item["inferred_status"])
            item["review_status"] = "expired" if expired else (manual_status or item["inferred_status"])
            item["verification_expired"] = expired
            item["source_version"] = {
                "indexed_git_head": item.get("git_head"),
                "reviewed_git_head": item.get("manual_git_head"),
                "current_evidence_hash": current_hash,
                "reviewed_evidence_hash": item.get("manual_evidence_hash"),
            }
            if expired:
                warnings.append(f"{item['project_name']}:{item['name']} verification expired; source evidence changed")
        results.sort(key=lambda item: {"verified": 0, "expired": 1, "inferred": 2, "unverified": 3}.get(item["status"], 4))
        return {"status": "ok", "query": query, "terms": terms, "results": results, "warnings": list(dict.fromkeys(warnings))}

    def _capability_evidence_fingerprint(self, conn: sqlite3.Connection, capability_id: int) -> str:
        """Hash the current source bytes and evidence ranges for one capability."""

        rows = conn.execute(
            """SELECT f.relative_path,f.sha256,p.path,e.start_line,e.end_line
                 FROM capability_evidence e
                 JOIN files f ON f.file_id=e.file_id
                 JOIN projects p ON p.project_id=f.project_id
                WHERE e.capability_id=?
                ORDER BY f.relative_path,e.start_line,e.end_line""",
            (capability_id,),
        ).fetchall()
        digest = hashlib.sha256()
        for row in rows:
            current_hash = row["sha256"]
            try:
                current_hash = _sha256(allowed_source_path(Path(row["path"]), row["relative_path"], self.cfg))
            except (OSError, ValueError):
                current_hash = "missing"
            digest.update(f"{row['relative_path']}\0{row['start_line']}\0{row['end_line']}\0{current_hash}\n".encode("utf-8"))
        return digest.hexdigest()

    def confirm_capability(
        self,
        project_id: str,
        name: str,
        status: str,
        label: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Maintain a Hub-local human review without changing source files."""

        if status not in {"verified", "inferred", "unverified"}:
            return {"status": "invalid_request", "warnings": ["status must be verified, inferred, or unverified"]}
        with connect(self.cfg.db_path) as conn:
            row = conn.execute(
                """SELECT c.capability_id,c.label,p.git_head
                     FROM capabilities c JOIN projects p ON p.project_id=c.project_id
                    WHERE c.project_id=? AND c.name=?""",
                (project_id, name),
            ).fetchone()
            if not row:
                return {"status": "not_found", "warnings": ["capability is not indexed for this project"]}
            reviewed_at = utc_now()
            evidence_hash = self._capability_evidence_fingerprint(conn, int(row["capability_id"]))
            conn.execute(
                """UPDATE capabilities
                      SET manual_status=?,manual_label=?,manual_note=?,reviewed_at=?,
                          manual_git_head=?,manual_evidence_hash=?,updated_at=?
                    WHERE capability_id=?""",
                (
                    status,
                    label.strip() if label and label.strip() else None,
                    note.strip() if note and note.strip() else None,
                    reviewed_at,
                    row["git_head"],
                    evidence_hash,
                    reviewed_at,
                    row["capability_id"],
                ),
            )
            conn.commit()
        return {
            "status": "ok",
            "project_id": project_id,
            "name": name,
            "effective_status": status,
            "label": label.strip() if label and label.strip() else row["label"],
            "reviewed_at": reviewed_at,
            "source_version": {"reviewed_git_head": row["git_head"], "reviewed_evidence_hash": evidence_hash},
            "warnings": ["Hub-local review metadata only; source project was not modified"],
        }

    def find_symbols(self, name: str, project_id: str | None = None, kind: str | None = None, limit: int = 20) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute("SELECT s.name,s.kind,s.start_line,s.end_line,s.signature,s.source,f.file_id,f.relative_path,p.project_id,p.name AS project_name,p.path,p.git_head,p.branch,p.dirty FROM symbols s JOIN files f ON f.file_id=s.file_id JOIN projects p ON p.project_id=f.project_id WHERE lower(s.name)=lower(?) AND (? IS NULL OR p.project_id=?) AND (? IS NULL OR s.kind=?) ORDER BY p.name,f.relative_path,s.start_line LIMIT ?", (name, project_id, project_id, kind, kind, limit)).fetchall()
        results = [dict(row) for row in rows]
        for item in results:
            item["dirty"] = None if item["dirty"] is None else bool(item["dirty"])
        return {"status": "degraded", "provider": "fallback-static", "serena": "unavailable", "results": results, "warnings": ["Serena is not installed; static symbols are used"]}

    def find_ui(self, query: str, limit: int = 12, project_id: str | None = None) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        terms = _query_terms(query)
        conditions = ["(" + " OR ".join("u.search_text LIKE ?" for _ in terms) + ")"]
        params: list[Any] = [f"%{term}%" for term in terms]
        if project_id:
            conditions.append("u.project_id=?")
            params.append(project_id)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute(
                f"""SELECT u.*,p.name AS project_name,p.path,p.git_head,p.branch,p.dirty,
                           p.languages_json,p.frameworks_json,p.markers_json,
                           f.file_id,f.relative_path
                      FROM ui_assets u
                      JOIN projects p ON p.project_id=u.project_id
                      LEFT JOIN files f ON f.file_id=u.file_id
                     WHERE p.excluded=0 AND {' AND '.join(conditions)}
                     ORDER BY u.name LIMIT ?""",
                (*params, limit),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("relative_path"):
                try:
                    allowed_source_path(Path(item["path"]), item["relative_path"], self.cfg)
                except (OSError, ValueError):
                    continue
            item["features"] = json.loads(item.pop("features_json"))
            item["languages"] = json.loads(item.pop("languages_json"))
            item["frameworks"] = json.loads(item.pop("frameworks_json"))
            item["markers"] = json.loads(item.pop("markers_json"))
            item["screenshot_url"] = f"/assets/{item['asset_id']}" if item["screenshot_status"] == "available" else None
            item["dirty"] = None if item["dirty"] is None else bool(item["dirty"])
            results.append(item)
        return {"status": "ok", "query": query, "terms": terms, "results": results, "warnings": ["No real screenshot is claimed unless screenshot_status=available"]}

    def get_source(self, project_id: str, file_id: int, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        with connect(self.cfg.db_path, readonly=True) as conn:
            row = conn.execute("SELECT f.*,p.path,p.git_head,p.dirty FROM files f JOIN projects p ON p.project_id=f.project_id WHERE f.project_id=? AND f.file_id=?", (project_id, file_id)).fetchone()
        if not row:
            return {"status": "not_found", "warnings": ["file is not indexed"]}
        try:
            path = allowed_source_path(Path(row["path"]), row["relative_path"], self.cfg)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError) as exc:
            return {"status": "denied", "warnings": [str(exc)]}
        start = max(1, start_line)
        end = min(len(lines), end_line or start + self.cfg.limits.max_snippet_lines - 1, start + self.cfg.limits.max_snippet_lines - 1)
        current_hash = _sha256(path)
        return {"status": "ok", "project_id": project_id, "file_id": file_id, "relative_path": row["relative_path"], "start_line": start, "end_line": end, "text": "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[: self.cfg.limits.max_chars], "git_head": row["git_head"], "dirty": bool(row["dirty"]) if row["dirty"] is not None else None, "stale": current_hash != row["sha256"], "warnings": [] if current_hash == row["sha256"] else ["source changed since indexing"]}

    def ui_detail(self, asset_id: str) -> dict[str, Any]:
        requested_asset_id = asset_id
        asset_id = self._resolve_asset_id(asset_id)
        with connect(self.cfg.db_path, readonly=True) as conn:
            row = conn.execute("SELECT u.*,p.name AS project_name,p.project_id,p.path,p.git_head,p.branch,p.dirty,f.file_id,f.relative_path,l.start_line,l.end_line FROM ui_assets u JOIN projects p ON p.project_id=u.project_id LEFT JOIN files f ON f.file_id=u.file_id LEFT JOIN ui_source_links l ON l.asset_id=u.asset_id WHERE u.asset_id=?", (asset_id,)).fetchone()
        if not row:
            return {"status": "not_found", "warnings": []}
        result = dict(row)
        result["features"] = json.loads(result.pop("features_json"))
        result["dirty"] = None if result["dirty"] is None else bool(result["dirty"])
        result["requested_asset_id"] = requested_asset_id
        result["asset_id_alias"] = requested_asset_id if requested_asset_id != asset_id else None
        result["screenshot_url"] = f"/assets/{asset_id}" if result["screenshot_status"] == "available" else None
        result["reference_prompt"] = f"参考 UI 资产 {asset_id}：项目 {result['project_name']}，源码 {result['relative_path']} 行 {result['start_line']}-{result['end_line']}。只借鉴布局/视觉线索，先核验源码和许可证。"
        return {"status": "ok", "asset": result, "warnings": []}

    def _resolve_asset_id(self, asset_id: str) -> str:
        current = asset_id
        with connect(self.cfg.db_path, readonly=True) as conn:
            for _ in range(8):
                row = conn.execute("SELECT new_asset_id FROM ui_asset_aliases WHERE old_asset_id=?", (current,)).fetchone()
                if not row or row[0] == current:
                    break
                current = row[0]
        return current

    def suggest_reuse(self, requirement: str, target_stack: str | None = None, limit: int = 3) -> dict[str, Any]:
        """Return evidence-shaped reuse candidates without claiming keyword reuse.

        Functional candidates are direct only after a current manual review and
        an explicit target-stack match.  UI candidates are always visual
        references; their existence never proves that the behavior is reusable.
        """

        limit = min(max(1, limit), 3)
        capabilities = self.find_capability(requirement, limit)
        ui_assets = self.find_ui(requirement, limit)
        target_tokens = set(re.findall(r"[a-z0-9+#.-]+", (target_stack or "").casefold()))

        def enrich(item: dict[str, Any], kind: str) -> dict[str, Any]:
            languages = list(item.get("languages", []))
            frameworks = list(item.get("frameworks", []))
            markers = list(item.get("markers", []))
            stack_tokens = {str(value).casefold() for value in languages + frameworks}
            overlap = bool(target_tokens & stack_tokens)
            if not target_stack:
                risk = "unknown"
            elif overlap:
                risk = "low" if kind == "capability" and item.get("status") == "verified" else "medium"
            else:
                risk = "high"

            if kind == "ui":
                reuse_type = "visual_reference"
            elif item.get("status") in {"expired", "unverified"}:
                reuse_type = "not_recommended"
            elif item.get("status") == "verified" and overlap:
                reuse_type = "reuse_direct"
            else:
                reuse_type = "adapt"

            evidence_source = {
                "project_id": item.get("project_id"),
                "project_name": item.get("project_name"),
                "relative_path": item.get("relative_path"),
                "file_id": item.get("file_id"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "reason": item.get("reason") or item.get("match_reason") or "ui source mapping",
                "git_head": item.get("git_head"),
                "dirty": item.get("dirty"),
            }
            if kind == "ui":
                evidence_source["screenshot_status"] = item.get("screenshot_status")
            return {
                **item,
                "candidate_kind": kind,
                "candidate_stack": {"languages": languages, "frameworks": frameworks},
                "dependency_clues": [f"marker:{marker}" for marker in markers]
                + [f"framework:{framework}" for framework in frameworks],
                "evidence_source": evidence_source,
                "adaptation_risk": risk,
                "reuse_type": reuse_type,
                "target_stack_match": overlap if target_stack else None,
            }

        candidates = [enrich(item, "capability") for item in capabilities.get("results", [])[:limit]]
        ui_candidates = [enrich(item, "ui") for item in ui_assets.get("results", [])[:limit]]
        return {
            "status": "ok",
            "source": "indexed-evidence",
            "requirement": requirement,
            "target_stack": target_stack,
            "candidates": candidates,
            "ui_candidates": ui_candidates,
            "reuse_types": sorted({item["reuse_type"] for item in candidates + ui_candidates}) or ["unknown"],
            "warnings": [
                "Candidates are evidence-backed leads, not a declaration that a feature can be copied directly; inspect evidence, dependencies, license and tests before implementation.",
            ],
        }

    def import_screenshot(self, asset_id: str, source_path: Path) -> dict[str, Any]:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if source_path.suffix.lower() not in SCREENSHOT_EXTENSIONS:
            return {"status": "invalid_request", "warnings": ["screenshot must be png, jpg, jpeg, webp, or gif"]}
        requested_asset_id = asset_id
        asset_id = self._resolve_asset_id(asset_id)
        with connect(self.cfg.db_path) as conn:
            row = conn.execute("SELECT asset_id FROM ui_assets WHERE asset_id=?", (asset_id,)).fetchone()
            if not row:
                return {"status": "not_found", "warnings": ["asset is not indexed"]}
        target = self.cfg.gallery_dir / "assets" / f"{asset_id}{source_path.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        with connect(self.cfg.db_path) as conn:
            conn.execute("UPDATE ui_assets SET screenshot_status='available',screenshot_path=?,updated_at=? WHERE asset_id=?", (str(target.relative_to(self.cfg.project_root).as_posix()), utc_now(), asset_id))
            conn.commit()
        return {"status": "ok", "asset_id": asset_id, "requested_asset_id": requested_asset_id, "screenshot_path": str(target)}

    def status(self) -> dict[str, Any]:
        with connect(self.cfg.db_path, readonly=True) as conn:
            counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("projects", "files", "symbols", "capabilities", "ui_assets", "index_runs", "index_errors")}
            last = conn.execute("SELECT * FROM index_runs ORDER BY run_id DESC LIMIT 1").fetchone()
            last_successful = conn.execute(
                """SELECT * FROM index_runs
                   WHERE status='ok' AND coverage_scope='root' AND projects_total > 0
                   ORDER BY finished_at DESC, run_id DESC LIMIT 1""",
            ).fetchone()
            last_failure = conn.execute(
                """SELECT * FROM index_runs
                   WHERE status IN ('error', 'partial', 'interrupted') OR errors > 0
                   ORDER BY run_id DESC LIMIT 1""",
            ).fetchone()
            failure_errors = []
            if last_failure:
                failure_errors = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT error_type,message,project_id,relative_path
                           FROM index_errors WHERE run_id=? ORDER BY error_id LIMIT 3""",
                        (last_failure["run_id"],),
                    ).fetchall()
                ]
            progress = []
            if last:
                progress = [dict(row) for row in conn.execute("SELECT * FROM index_project_runs WHERE run_id=? ORDER BY ordinal", (last["run_id"],)).fetchall()]
        last_dict = dict(last) if last else None
        if last_dict:
            for key in ("stage_timings_json", "stage_counts_json"):
                raw = last_dict.get(key)
                try:
                    last_dict[key.removesuffix("_json")] = json.loads(raw or "{}")
                except (TypeError, json.JSONDecodeError):
                    last_dict[key.removesuffix("_json")] = {}
        for item in progress:
            for key in ("stage_timings_json", "stage_counts_json"):
                raw = item.get(key)
                try:
                    item[key.removesuffix("_json")] = json.loads(raw or "{}")
                except (TypeError, json.JSONDecodeError):
                    item[key.removesuffix("_json")] = {}
        last_successful_dict = dict(last_successful) if last_successful else None
        last_attempt_at = None
        last_attempt_status = None
        current_state = "unknown"
        if last_dict:
            last_attempt_at = last_dict.get("finished_at") or last_dict.get("started_at")
            last_attempt_status = last_dict.get("status")
            current_state = last_attempt_status or "unknown"

        last_successful_at = last_successful_dict.get("finished_at") if last_successful_dict else None
        age_seconds: float | None = None
        freshness_level = "unknown"
        threshold_seconds = max(1.0, float(self.cfg.limits.freshness_stale_after_hours) * 3600.0)
        if last_successful_at:
            try:
                completed_at = datetime.fromisoformat(last_successful_at.replace("Z", "+00:00"))
                age_seconds = max(0.0, (datetime.now(timezone.utc) - completed_at).total_seconds())
                freshness_level = "fresh" if age_seconds <= threshold_seconds else "stale"
            except (TypeError, ValueError, OverflowError):
                freshness_level = "unknown"
        else:
            freshness_level = "unknown"

        last_failure_summary = None
        if last_failure:
            last_failure_summary = {
                "run_id": last_failure["run_id"],
                "status": last_failure["status"],
                "finished_at": last_failure["finished_at"],
                "errors": last_failure["errors"],
                "coverage_scope": last_failure["coverage_scope"],
                "errors_detail": failure_errors,
            }
        return {
            "status": "ok",
            "db": str(self.cfg.db_path),
            "counts": counts,
            "last_index": last_dict,
            "project_progress": progress,
            "current_state": current_state,
            "last_attempt_at": last_attempt_at,
            "last_attempt_status": last_attempt_status,
            "last_successful_index_at": last_successful_at,
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "freshness_level": freshness_level,
            "freshness": {
                "level": freshness_level,
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "threshold_seconds": round(threshold_seconds, 3),
                "last_successful_index_at": last_successful_at,
                "coverage_scope": last_successful_dict.get("coverage_scope") if last_successful_dict else None,
            },
            "last_successful_index_run_id": last_successful_dict.get("run_id") if last_successful_dict else None,
            "last_failure_summary": last_failure_summary,
        }

