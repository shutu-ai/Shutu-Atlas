from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from typing import Any

from ..config import AtlasConfig
from ..discovery import ProjectRecord, iter_project_files, safe_source_path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
  is_git INTEGER NOT NULL, git_head TEXT, branch TEXT, dirty INTEGER,
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
  name TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS index_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  mode TEXT NOT NULL, projects_seen INTEGER NOT NULL DEFAULT 0, files_indexed INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS index_errors (
  error_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES index_runs(run_id) ON DELETE CASCADE,
  project_id TEXT, relative_path TEXT, error_type TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_content USING fts5(
  project_id UNINDEXED, file_id UNINDEXED, relative_path, language, content,
  tokenize='unicode61 remove_diacritics 2'
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


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect(db_path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(cfg: AtlasConfig) -> None:
    cfg.ensure_local_dirs()
    with connect(cfg.db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def detect_capabilities(text: str) -> list[dict[str, Any]]:
    folded = text.casefold()
    lines = text.splitlines()
    results: list[dict[str, Any]] = []
    for name, label, needles in CAPABILITY_RULES:
        hits = [i for i, line in enumerate(lines, 1) if any(needle.casefold() in line.casefold() for needle in needles)]
        if hits:
            status = "verified" if len(hits) >= 2 and any("test" in line.casefold() or "assert" in line.casefold() for line in lines) else "inferred"
            results.append({"name": name, "label": label, "status": status, "line": hits[0], "snippet": _snippet(lines, hits[0]), "reason": f"关键词命中: {', '.join(needles[:3])}"})
    return results


def detect_ui_asset(relative_path: str, text: str) -> dict[str, Any] | None:
    suffix = Path(relative_path).suffix.lower()
    if suffix not in UI_EXTENSIONS:
        return None
    folded = text.casefold()
    features: list[str] = []
    for needle, label in (("kpi", "KPI"), ("echarts", "ECharts"), ("chart", "图表"), ("filter", "筛选器"), ("table", "表格"), ("dark", "深色主题"), ("--", "CSS 变量"), ("grid", "Grid 布局"), ("tailwind", "Tailwind")):
        if needle in folded:
            features.append(label)
    name = Path(relative_path).stem
    asset_id = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:20]
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

    def _upsert_project(self, conn: sqlite3.Connection, project: ProjectRecord) -> None:
        conn.execute(
            """INSERT INTO projects(project_id,name,path,is_git,git_head,branch,dirty,languages_json,frameworks_json,markers_json,discovery_kind,excluded,exclusion_reason,indexed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET name=excluded.name,path=excluded.path,is_git=excluded.is_git,git_head=excluded.git_head,branch=excluded.branch,dirty=excluded.dirty,languages_json=excluded.languages_json,frameworks_json=excluded.frameworks_json,markers_json=excluded.markers_json,discovery_kind=excluded.discovery_kind,excluded=excluded.excluded,exclusion_reason=excluded.exclusion_reason,indexed_at=excluded.indexed_at""",
            (project.project_id, project.name, project.path, int(project.is_git), project.git_head, project.branch, None if project.dirty is None else int(project.dirty), json.dumps(project.languages), json.dumps(project.frameworks), json.dumps(project.markers), project.discovery_kind, int(project.excluded), project.exclusion_reason, utc_now()),
        )

    def index(self, projects: Iterable[ProjectRecord], changed_only: bool = False) -> dict[str, Any]:
        self.cfg.ensure_local_dirs()
        with connect(self.cfg.db_path) as conn:
            cur = conn.execute("INSERT INTO index_runs(started_at,mode,status) VALUES(?,?,?)", (utc_now(), "changed-only" if changed_only else "full", "running"))
            run_id = cur.lastrowid
            conn.commit()
            counts = {"projects_seen": 0, "files_indexed": 0, "errors": 0}
            for project in projects:
                if project.excluded:
                    continue
                counts["projects_seen"] += 1
                try:
                    counts["files_indexed"] += self._index_project(conn, project, changed_only)
                    conn.commit()
                except Exception as exc:  # keep other projects independently indexable
                    conn.rollback()
                    counts["errors"] += 1
                    conn.execute("INSERT INTO index_errors(run_id,project_id,error_type,message,created_at) VALUES(?,?,?,?,?)", (run_id, project.project_id, type(exc).__name__, str(exc)[:1000], utc_now()))
                    conn.commit()
            conn.execute("UPDATE index_runs SET finished_at=?,projects_seen=?,files_indexed=?,errors=?,status=? WHERE run_id=?", (utc_now(), counts["projects_seen"], counts["files_indexed"], counts["errors"], "ok" if not counts["errors"] else "partial", run_id))
            conn.commit()
            return {"run_id": run_id, **counts, "status": "ok" if not counts["errors"] else "partial"}

    def _index_project(self, conn: sqlite3.Connection, project: ProjectRecord, changed_only: bool) -> int:
        now = utc_now()
        self._upsert_project(conn, project)
        old = {row["relative_path"]: dict(row) for row in conn.execute("SELECT * FROM files WHERE project_id=?", (project.project_id,))}
        seen: set[str] = set()
        changed = 0
        for path, relative in iter_project_files(project, self.cfg):
            seen.add(relative)
            stat = path.stat()
            digest = _sha256(path)
            previous = old.get(relative)
            if changed_only and previous and previous["sha256"] == digest and previous["size_bytes"] == stat.st_size and previous["modified_ns"] == stat.st_mtime_ns:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[: self.cfg.limits.max_chars * 64]
            language = _language(relative)
            conn.execute("INSERT INTO files(project_id,relative_path,language,size_bytes,modified_ns,sha256,is_working_tree,indexed_at) VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(project_id,relative_path) DO UPDATE SET language=excluded.language,size_bytes=excluded.size_bytes,modified_ns=excluded.modified_ns,sha256=excluded.sha256,is_working_tree=1,indexed_at=excluded.indexed_at", (project.project_id, relative, language, stat.st_size, stat.st_mtime_ns, digest, now))
            file_id = conn.execute("SELECT file_id FROM files WHERE project_id=? AND relative_path=?", (project.project_id, relative)).fetchone()[0]
            conn.execute("DELETE FROM fts_content WHERE file_id=?", (file_id,))
            conn.execute("INSERT INTO fts_content(project_id,file_id,relative_path,language,content) VALUES(?,?,?,?,?)", (project.project_id, file_id, relative, language, text))
            conn.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
            conn.executemany("INSERT INTO symbols(file_id,name,kind,start_line,end_line,signature,source) VALUES(?,?,?,?,?,?,?)", [(file_id, s["name"], s["kind"], s["start_line"], s["end_line"], s["signature"], s["source"]) for s in extract_symbols(text, language)])
            conn.execute("DELETE FROM capability_evidence WHERE file_id=?", (file_id,))
            for cap in detect_capabilities(text):
                conn.execute("INSERT INTO capabilities(project_id,name,label,status,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET label=excluded.label,status=CASE WHEN capabilities.status='verified' THEN 'verified' ELSE excluded.status END,updated_at=excluded.updated_at", (project.project_id, cap["name"], cap["label"], cap["status"], now))
                cap_id = conn.execute("SELECT capability_id FROM capabilities WHERE project_id=? AND name=?", (project.project_id, cap["name"])).fetchone()[0]
                conn.execute("INSERT INTO capability_evidence(capability_id,file_id,start_line,end_line,snippet,reason) VALUES(?,?,?,?,?,?)", (cap_id, file_id, cap["line"], cap["line"], cap["snippet"], cap["reason"]))
            conn.execute("DELETE FROM ui_source_links WHERE file_id=?", (file_id,))
            conn.execute("DELETE FROM ui_assets WHERE file_id=?", (file_id,))
            asset = detect_ui_asset(relative, text)
            if asset:
                conn.execute("INSERT OR REPLACE INTO ui_assets(asset_id,project_id,file_id,asset_type,name,search_text,features_json,screenshot_status,screenshot_path,confidence,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (asset["asset_id"], project.project_id, file_id, asset["asset_type"], asset["name"], asset["search_text"], json.dumps(asset["features"], ensure_ascii=False), "unavailable", None, "inferred", now))
                conn.execute("INSERT OR REPLACE INTO ui_source_links(asset_id,file_id,start_line,end_line) VALUES(?,?,?,?)", (asset["asset_id"], file_id, asset["start_line"], asset["end_line"]))
            changed += 1
        for relative, row in old.items():
            if relative not in seen:
                conn.execute("DELETE FROM files WHERE file_id=?", (row["file_id"],))
                conn.execute("DELETE FROM fts_content WHERE file_id=?", (row["file_id"],))
        conn.execute("DELETE FROM capabilities WHERE project_id=? AND capability_id NOT IN (SELECT DISTINCT c.capability_id FROM capabilities c JOIN capability_evidence e ON e.capability_id=c.capability_id WHERE c.project_id=?)", (project.project_id, project.project_id))
        conn.execute("UPDATE projects SET file_count=(SELECT count(*) FROM files WHERE project_id=?) WHERE project_id=?", (project.project_id, project.project_id))
        return changed

    def list_projects(self, filter_text: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute("SELECT * FROM projects WHERE excluded=0 AND (? IS NULL OR name LIKE ? OR path LIKE ?) ORDER BY name LIMIT ?", (filter_text, f"%{filter_text}%" if filter_text else None, f"%{filter_text}%" if filter_text else None, limit)).fetchall()
        return [self._project_dict(row) for row in rows]

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
        terms = _query_terms(query)
        fts_query = " OR ".join('"' + t.replace('"', ' ') + '"' for t in terms)
        results: list[dict[str, Any]] = []
        with connect(self.cfg.db_path, readonly=True) as conn:
            sql = "SELECT f.project_id,f.file_id,f.relative_path,f.language,s.highlight FROM fts_content f JOIN (SELECT project_id,file_id,relative_path,language,content,highlight(fts_content,4,'[HIGHLIGHT]','[/HIGHLIGHT]') AS highlight FROM fts_content WHERE fts_content MATCH ?) s ON s.file_id=f.file_id WHERE (? IS NULL OR f.project_id=?) AND (? IS NULL OR f.language=?) LIMIT ?"
            try:
                rows = conn.execute(sql, (fts_query, project_id, project_id, language, language, limit)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                results.append({"project_id": row["project_id"], "file_id": row["file_id"], "relative_path": row["relative_path"], "language": row["language"], "snippet": row["highlight"][: self.cfg.limits.max_chars], "match_reason": "fts", "evidence": "SQLite FTS5 BM25 candidate"})
        for item in self._rg_search(query, limit, project_id, language):
            if not any(r["project_id"] == item["project_id"] and r["relative_path"] == item["relative_path"] and r.get("line") == item.get("line") for r in results):
                results.append(item)
            if len(results) >= limit:
                break
        return {"status": "ok", "query": query, "terms": terms, "results": results[:limit], "warnings": [] if shutil.which("rg") else ["rg_unavailable"]}

    def _rg_search(self, query: str, limit: int, project_id: str | None, language: str | None) -> list[dict[str, Any]]:
        if not shutil.which("rg"):
            return []
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute("SELECT project_id,path FROM projects WHERE excluded=0 AND (? IS NULL OR project_id=?)", (project_id, project_id)).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            try:
                proc = subprocess.run(["rg", "--line-number", "--no-heading", "--color", "never", "--fixed-strings", "--max-count", "3", "--glob", "!.git/**", "--glob", "!.local/**", "--glob", "!node_modules/**", "--glob", "!.env*", "--", query, row["path"]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.cfg.limits.command_timeout_seconds, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            root = Path(row["path"]).resolve()
            for raw in proc.stdout.splitlines():
                match = re.match(r"^(.*):(\d+):(.*)$", raw)
                if not match:
                    continue
                path, line, text = match.groups()
                try:
                    rel = Path(path).resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                if language and _language(rel) != language:
                    continue
                with connect(self.cfg.db_path, readonly=True) as local:
                    file_row = local.execute("SELECT file_id FROM files WHERE project_id=? AND relative_path=?", (row["project_id"], rel)).fetchone()
                results.append({"project_id": row["project_id"], "file_id": file_row[0] if file_row else None, "relative_path": rel, "language": _language(rel), "line": int(line), "snippet": text[: self.cfg.limits.max_chars], "match_reason": "regex", "evidence": "ripgrep fixed-string match"})
                if len(results) >= limit:
                    return results
        return results

    def find_capability(self, query: str, limit: int = 10, project_filter: str | None = None) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        terms = _query_terms(query)
        with connect(self.cfg.db_path, readonly=True) as conn:
            term_conditions = ["(c.label LIKE ? OR c.name LIKE ? OR e.snippet LIKE ?)"] * len(terms)
            conditions = ["(" + " OR ".join(term_conditions) + ")"]
            params: list[Any] = []
            for term in terms:
                params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
            if project_filter:
                conditions.append("(p.name LIKE ? OR p.project_id=?)")
                params.extend([f"%{project_filter}%", project_filter])
            rows = conn.execute(f"SELECT c.name,c.label,c.status,p.project_id,p.name AS project_name,p.path,e.file_id,f.relative_path,e.start_line,e.end_line,e.snippet,e.reason FROM capabilities c JOIN projects p ON p.project_id=c.project_id JOIN capability_evidence e ON e.capability_id=c.capability_id JOIN files f ON f.file_id=e.file_id WHERE {' AND '.join(conditions)} ORDER BY CASE c.status WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 ELSE 2 END, p.name LIMIT ?", (*params, limit)).fetchall()
        return {"status": "ok", "query": query, "terms": terms, "results": [dict(row) for row in rows], "warnings": []}

    def find_symbols(self, name: str, project_id: str | None = None, kind: str | None = None, limit: int = 20) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute("SELECT s.name,s.kind,s.start_line,s.end_line,s.signature,s.source,f.file_id,f.relative_path,p.project_id,p.name AS project_name,p.path FROM symbols s JOIN files f ON f.file_id=s.file_id JOIN projects p ON p.project_id=f.project_id WHERE lower(s.name)=lower(?) AND (? IS NULL OR p.project_id=?) AND (? IS NULL OR s.kind=?) ORDER BY p.name,f.relative_path,s.start_line LIMIT ?", (name, project_id, project_id, kind, kind, limit)).fetchall()
        return {"status": "degraded", "provider": "fallback-static", "serena": "unavailable", "results": [dict(row) for row in rows], "warnings": ["Serena is not installed; static symbols are used"]}

    def find_ui(self, query: str, limit: int = 12, project_id: str | None = None) -> dict[str, Any]:
        limit = min(max(1, limit), self.cfg.limits.max_results)
        terms = _query_terms(query)
        conditions = ["u.search_text LIKE ?"]
        params: list[Any] = [f"%{terms[0]}%"]
        if project_id:
            conditions.append("u.project_id=?")
            params.append(project_id)
        with connect(self.cfg.db_path, readonly=True) as conn:
            rows = conn.execute(f"SELECT u.*,p.name AS project_name,p.path,f.file_id,f.relative_path FROM ui_assets u JOIN projects p ON p.project_id=u.project_id LEFT JOIN files f ON f.file_id=u.file_id WHERE {' AND '.join(conditions)} ORDER BY u.name LIMIT ?", (*params, limit)).fetchall()
        results = [dict(row) for row in rows]
        for item in results:
            item["features"] = json.loads(item.pop("features_json"))
        return {"status": "ok", "query": query, "terms": terms, "results": results, "warnings": ["No real screenshot is claimed unless screenshot_status=available"]}

    def get_source(self, project_id: str, file_id: int, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        with connect(self.cfg.db_path, readonly=True) as conn:
            row = conn.execute("SELECT f.*,p.path,p.git_head,p.dirty FROM files f JOIN projects p ON p.project_id=f.project_id WHERE f.project_id=? AND f.file_id=?", (project_id, file_id)).fetchone()
        if not row:
            return {"status": "not_found", "warnings": ["file is not indexed"]}
        try:
            path = safe_source_path(Path(row["path"]), row["relative_path"])
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError) as exc:
            return {"status": "denied", "warnings": [str(exc)]}
        start = max(1, start_line)
        end = min(len(lines), end_line or start + self.cfg.limits.max_snippet_lines - 1, start + self.cfg.limits.max_snippet_lines - 1)
        current_hash = _sha256(path)
        return {"status": "ok", "project_id": project_id, "file_id": file_id, "relative_path": row["relative_path"], "start_line": start, "end_line": end, "text": "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[: self.cfg.limits.max_chars], "git_head": row["git_head"], "dirty": bool(row["dirty"]) if row["dirty"] is not None else None, "stale": current_hash != row["sha256"], "warnings": [] if current_hash == row["sha256"] else ["source changed since indexing"]}

    def ui_detail(self, asset_id: str) -> dict[str, Any]:
        with connect(self.cfg.db_path, readonly=True) as conn:
            row = conn.execute("SELECT u.*,p.name AS project_name,p.project_id,p.path,f.file_id,f.relative_path,l.start_line,l.end_line FROM ui_assets u JOIN projects p ON p.project_id=u.project_id LEFT JOIN files f ON f.file_id=u.file_id LEFT JOIN ui_source_links l ON l.asset_id=u.asset_id WHERE u.asset_id=?", (asset_id,)).fetchone()
        if not row:
            return {"status": "not_found", "warnings": []}
        result = dict(row)
        result["features"] = json.loads(result.pop("features_json"))
        result["reference_prompt"] = f"参考 UI 资产 {asset_id}：项目 {result['project_name']}，源码 {result['relative_path']} 行 {result['start_line']}-{result['end_line']}。只借鉴布局/视觉线索，先核验源码和许可证。"
        return {"status": "ok", "asset": result, "warnings": []}

    def import_screenshot(self, asset_id: str, source_path: Path) -> dict[str, Any]:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
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
        return {"status": "ok", "asset_id": asset_id, "screenshot_path": str(target)}

    def status(self) -> dict[str, Any]:
        with connect(self.cfg.db_path, readonly=True) as conn:
            counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("projects", "files", "symbols", "capabilities", "ui_assets", "index_runs", "index_errors")}
            last = conn.execute("SELECT * FROM index_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        return {"status": "ok", "db": str(self.cfg.db_path), "counts": counts, "last_index": dict(last) if last else None}

