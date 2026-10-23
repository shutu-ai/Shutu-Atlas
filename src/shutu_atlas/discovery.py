from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import os
import stat as stat_module
import time
from pathlib import Path
import subprocess
from typing import Any, Iterator

from .config import AtlasConfig
from .index.metrics import StageMetrics, elapsed_ms, timed


MARKERS = {
    "pyproject.toml", "requirements.txt", "setup.py", "package.json", "pnpm-lock.yaml",
    "yarn.lock", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Dockerfile",
    "manage.py", "vite.config.ts", "vite.config.js", "README.md", "Readme.md",
}
TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".vue", ".html", ".css", ".scss",
    ".less", ".json", ".toml", ".yaml", ".yml", ".md", ".rst", ".go", ".rs", ".java",
    ".kt", ".cs", ".cpp", ".c", ".h", ".sql", ".sh", ".ps1", ".bat", ".xml",
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development", "id_rsa",
    "credentials.json", "credentials.toml", "secrets.json", "secrets.yaml",
    "secret.key", "token.txt", "access_token", "client_secret", ".npmrc",
    ".pypirc", ".netrc",
}
SENSITIVE_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der", ".jks",
    ".keystore", ".asc", ".gpg",
}
SENSITIVE_DIR_NAMES = {".aws", ".ssh", ".gnupg", ".secrets", ".credentials"}
SENSITIVE_NAME_PARTS = (
    "secret", "credential", "token", "password", "passwd", "api-key", "api_key",
    "apikey", "private-key", "private_key",
)


def _is_excluded_directory_name(name: str, cfg: AtlasConfig) -> bool:
    return (
        name in cfg.excluded_dirs
        or name.startswith(".deploy-staging-")
        or name.startswith("pytest-cache-files-")
    )


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    name: str
    path: str
    is_git: bool
    git_head: str | None
    branch: str | None
    dirty: bool | None
    languages: list[str]
    frameworks: list[str]
    markers: list[str]
    discovery_kind: str
    excluded: bool = False
    exclusion_reason: str | None = None
    git_status_hash: str | None = None
    git_status_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ProjectFile:
    path: Path
    relative: str
    stat_result: os.stat_result


@dataclass(slots=True)
class ProjectScan:
    files: list[ProjectFile] = field(default_factory=list)
    scanned_bytes: int = 0
    eligible_total: int = 0
    skipped_count: int = 0
    skipped_files: int = 0
    skipped_dirs: int = 0
    truncated: bool = False
    metrics: StageMetrics = field(default_factory=StageMetrics)


def _run_git(path: Path, args: list[str], timeout: float) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_info(path: Path, timeout: float) -> tuple[bool, str | None, str | None, bool | None, float, str | None]:
    """Return Git metadata while keeping status subprocesses measurable.

    ``status --porcelain=v2 --branch`` includes the branch and HEAD oid, so a
    normal discovery uses two Git processes instead of the previous four.  A
    fallback ``rev-parse HEAD`` is only needed for an unborn/atypical HEAD.
    """

    started = time.perf_counter_ns()
    top = _run_git(path, ["rev-parse", "--show-toplevel"], timeout)
    if not top:
        return False, None, None, None, elapsed_ms(started), None

    status = _run_git(path, ["status", "--porcelain=v2", "--branch", "--untracked-files=all"], timeout)
    if status is None:
        head = _run_git(path, ["rev-parse", "HEAD"], timeout)
        branch = _run_git(path, ["branch", "--show-current"], timeout)
        dirty = None
        status_hash = None
    else:
        head = None
        branch = None
        dirty = False
        for line in status.splitlines():
            if line.startswith("# branch.head "):
                branch = line.removeprefix("# branch.head ").strip() or None
            elif line.startswith("# branch.oid "):
                head = line.removeprefix("# branch.oid ").strip() or None
            elif line and not line.startswith("#"):
                dirty = True
        if head in {None, "(initial)", "(unknown)"}:
            head = _run_git(path, ["rev-parse", "HEAD"], timeout)
        if branch == "(detached)":
            branch = None
        status_hash = hashlib.sha256(status.encode("utf-8", errors="replace")).hexdigest()
    return True, head, branch, dirty, elapsed_ms(started), status_hash


def _project_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:16]


def is_reparse_point(path: Path, metrics: StageMetrics | None = None) -> bool:
    """Return True for Windows junctions/symlinks without following them."""
    started = time.perf_counter_ns()
    try:
        stat_result = path.stat(follow_symlinks=False)
        if metrics:
            metrics.add_count("stat_calls")
        attrs = getattr(stat_result, "st_file_attributes", 0)
        return bool(attrs & 0x400000) or stat_module.S_ISLNK(stat_result.st_mode)
    except OSError:
        if metrics:
            metrics.add_count("stat_errors")
        return True
    finally:
        if metrics:
            metrics.add_elapsed("stat", time.perf_counter_ns() - started)


def _read_marker(path: Path, marker: str) -> str:
    try:
        return (path / marker).read_text(encoding="utf-8", errors="replace")[:100_000]
    except OSError:
        return ""


def _detect_stack(path: Path, markers: list[str]) -> tuple[list[str], list[str]]:
    languages: set[str] = set()
    frameworks: set[str] = set()
    ext_map = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
               ".tsx": "TypeScript", ".vue": "Vue", ".go": "Go", ".rs": "Rust", ".java": "Java",
               ".cs": "C#"}
    for child in path.glob("*"):
        if child.is_file() and child.suffix.lower() in ext_map:
            languages.add(ext_map[child.suffix.lower()])
    if "pyproject.toml" in markers or "requirements.txt" in markers or "manage.py" in markers:
        languages.add("Python")
    if "go.mod" in markers:
        languages.add("Go")
    if "package.json" in markers:
        package = _read_marker(path, "package.json")
        languages.update({"TypeScript" if "typescript" in package.lower() or ".ts" in package else "JavaScript"})
        for needle, framework in (("vue", "Vue"), ("react", "React"), ("next", "Next.js"),
                                  ("echarts", "ECharts"), ("tailwind", "Tailwind"), ("vite", "Vite")):
            if needle in package.lower():
                frameworks.add(framework)
    if "pyproject.toml" in markers or "requirements.txt" in markers:
        text = " ".join(_read_marker(path, m).lower() for m in ("pyproject.toml", "requirements.txt"))
        for needle, framework in (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"),
                                  ("mcp", "MCP"), ("pytest", "pytest")):
            if needle in text:
                frameworks.add(framework)
    if "go.mod" in markers and "mcp" in _read_marker(path, "go.mod").lower():
        frameworks.add("MCP")
    return sorted(languages), sorted(frameworks)


def _is_candidate(path: Path) -> tuple[bool, str, list[str]]:
    if (path / ".git").exists():
        return True, "git", sorted(p.name for p in path.iterdir() if p.is_file() and p.name in MARKERS)
    markers: set[str] = set()
    try:
        for p in path.iterdir():
            if p.is_file() and p.name in MARKERS:
                markers.add(p.name)
        for child in path.iterdir():
            if child.is_dir() and child.name not in {".git", "node_modules", ".venv", "dist", "build"}:
                for p in child.iterdir():
                    if p.is_file() and p.name in MARKERS:
                        markers.add(p.name)
    except OSError:
        return False, "unreadable", []
    return bool(markers), "source", sorted(markers)


def discover_projects(cfg: AtlasConfig, report: dict[str, Any] | None = None) -> list[ProjectRecord]:
    started = time.perf_counter_ns()
    metrics = StageMetrics()
    found: dict[str, ProjectRecord] = {}
    counts = {
        "roots_seen": 0,
        "root_errors": 0,
        "directory_entries": 0,
        "skipped_directories": 0,
        "candidate_projects": 0,
        "git_projects": 0,
    }

    def add_candidate(path: Path, kind: str, markers: list[str]) -> None:
        is_git, head, branch, dirty, git_ms, git_status_hash = _git_info(path, cfg.limits.command_timeout_seconds)
        metrics.add_elapsed("git_status", int(git_ms * 1_000_000))
        metrics.add_count("git_commands", 2 if is_git else 1)
        with timed(metrics, "stack_detection"):
            languages, frameworks = _detect_stack(path, markers)
        record = ProjectRecord(
            project_id=_project_id(path), name=path.name, path=str(path.resolve()),
            is_git=is_git, git_head=head, branch=branch, dirty=dirty,
            languages=languages, frameworks=frameworks, markers=markers,
            discovery_kind=kind, git_status_hash=git_status_hash,
            git_status_ms=git_ms,
        )
        if cfg.include_projects and record.name not in cfg.include_projects and record.project_id not in cfg.include_projects:
            record.excluded, record.exclusion_reason = True, "not in include_projects"
        if record.name in cfg.exclude_projects or record.project_id in cfg.exclude_projects:
            record.excluded, record.exclusion_reason = True, "exclude_projects"
        found[record.project_id] = record
        counts["candidate_projects"] += 1
        if is_git:
            counts["git_projects"] += 1

    with timed(metrics, "directory_traversal"):
        for root in cfg.roots:
            counts["roots_seen"] += 1
            if not root.exists() or not root.is_dir():
                counts["root_errors"] += 1
                continue
            try:
                children = list(root.iterdir())
            except OSError:
                counts["root_errors"] += 1
                continue
            for path in children:
                counts["directory_entries"] += 1
                with timed(metrics, "path_check"):
                    reject = (
                        not path.is_dir()
                        or is_reparse_point(path, metrics)
                        or path.name.startswith(".")
                        or _is_excluded_directory_name(path.name, cfg)
                        or path.resolve() == cfg.project_root
                    )
                if reject:
                    counts["skipped_directories"] += 1
                    continue
                with timed(metrics, "path_check"):
                    candidate, kind, markers = _is_candidate(path)
                if not candidate:
                    continue
                try:
                    with timed(metrics, "path_check"):
                        direct_markers = [p.name for p in path.iterdir() if p.is_file() and p.name in MARKERS]
                except OSError:
                    continue
                if kind == "source" and not direct_markers:
                    nested = []
                    try:
                        children_of_candidate = list(path.iterdir())
                    except OSError:
                        children_of_candidate = []
                    for child in children_of_candidate:
                        with timed(metrics, "path_check"):
                            child_ok = child.is_dir() and not is_reparse_point(child, metrics) and not child.name.startswith(".")
                        if not child_ok:
                            continue
                        with timed(metrics, "path_check"):
                            child_candidate, child_kind, child_markers = _is_candidate(child)
                        if child_candidate and (child_kind == "git" or child_markers):
                            nested.append((child, child_kind, child_markers))
                    if nested:
                        for child, child_kind, child_markers in nested:
                            add_candidate(child, child_kind, child_markers)
                        continue
                add_candidate(path, kind, markers)

    projects = sorted(found.values(), key=lambda p: p.name.casefold())
    if report is not None:
        report.clear()
        report.update(
            {
                "instrumentation_version": "v2",
                "counts": {**counts, "projects_returned": len(projects), "projects_excluded": sum(1 for p in projects if p.excluded)},
                "timings_ms": {**metrics.timings_ms(), "total": elapsed_ms(started)},
                "operation_counts": dict(metrics.counts),
                "projects": [p.to_dict() for p in projects],
            }
        )
    return projects


def is_sensitive(path: Path) -> bool:
    """Return whether a path is outside the shared readable-file policy.

    This predicate is deliberately used by discovery, ripgrep and source reads.
    It is conservative for hidden credential-like names while leaving ordinary
    hidden project files such as ``.eslintrc`` available to the index.
    """

    folded_parts = [part.casefold() for part in path.parts]
    name = path.name.casefold()
    if name in {n.casefold() for n in SENSITIVE_NAMES}:
        return True
    if name.startswith(".env") or path.suffix.casefold() in SENSITIVE_SUFFIXES:
        return True
    if any(part in SENSITIVE_DIR_NAMES for part in folded_parts):
        return True
    return name.startswith(".") and any(part in name for part in SENSITIVE_NAME_PARTS)


def safe_source_path(project_root: Path, relative_path: str, metrics: StageMetrics | None = None) -> Path:
    """Resolve an indexed relative path without following links or escaping.

    Checking the unresolved path before calling ``resolve`` is important on
    Windows: resolving first would turn a symlink into its target and make a
    later ``is_symlink`` check ineffective.
    """

    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("relative path required")
    base = project_root.resolve()
    raw_target = base / relative
    current = base
    for part in relative.parts:
        current = current / part
        if current != base and is_reparse_point(current, metrics):
            raise ValueError("symlink source is not readable")
    target = raw_target.resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes project root")
    return target


def _allowed_source_path_with_stat(
    project_root: Path,
    relative_path: str,
    cfg: AtlasConfig,
    metrics: StageMetrics | None = None,
    assume_walked: bool = False,
) -> tuple[Path, os.stat_result]:
    """Return a path only when it belongs to the indexable file set.

    ``iter_project_files`` and all indexed source consumers call this helper so
    a file cannot be searchable or readable merely because ripgrep can see it.
    """

    relative = Path(relative_path)
    if any(_is_excluded_directory_name(part, cfg) for part in relative.parts):
        raise ValueError("path is in an excluded directory")
    base = Path(project_root) if assume_walked else project_root.resolve()
    raw_target = base / relative
    if is_sensitive(raw_target) or raw_target.suffix.lower() not in TEXT_EXTENSIONS:
        raise ValueError("path is not in the readable file set")
    if assume_walked:
        # ``scan_project_files`` already filtered every directory returned by
        # os.walk and still checks the leaf itself.  Rechecking every parent
        # component for every file was the dominant no-change cost on large
        # repositories.  Relative paths cannot escape because ``..`` and
        # absolute paths were rejected above.
        target = Path(project_root) / relative
        started = time.perf_counter_ns()
        try:
            stat_result = target.stat(follow_symlinks=False)
            if metrics:
                metrics.add_count("stat_calls")
            attrs = getattr(stat_result, "st_file_attributes", 0)
            if bool(attrs & 0x400000) or stat_module.S_ISLNK(stat_result.st_mode):
                raise ValueError("symlink source is not readable")
            if not stat_module.S_ISREG(stat_result.st_mode):
                raise ValueError("source file is not readable")
            if stat_result.st_size > cfg.limits.max_file_bytes:
                raise ValueError("source file exceeds the configured size limit")
            return target, stat_result
        except OSError as exc:
            raise ValueError("source file is not readable") from exc
        finally:
            if metrics:
                metrics.add_elapsed("stat", time.perf_counter_ns() - started)
    else:
        target = safe_source_path(project_root, relative_path, metrics)
    try:
        started = time.perf_counter_ns()
        stat_result = target.stat()
        if metrics:
            metrics.add_count("stat_calls")
        if not stat_module.S_ISREG(stat_result.st_mode):
            raise ValueError("source file is not readable")
        if stat_result.st_size > cfg.limits.max_file_bytes:
            raise ValueError("source file exceeds the configured size limit")
    except OSError as exc:
        raise ValueError("source file is not readable") from exc
    finally:
        if metrics:
            metrics.add_elapsed("stat", time.perf_counter_ns() - started)
    return target, stat_result


def allowed_source_path(project_root: Path, relative_path: str, cfg: AtlasConfig) -> Path:
    return _allowed_source_path_with_stat(project_root, relative_path, cfg)[0]


def scan_project_files(project: ProjectRecord, cfg: AtlasConfig) -> ProjectScan:
    """Scan one project once and retain safe paths plus their first stat.

    All consumers use the same allowed-file predicate.  The returned stat is
    the ordinary incremental fast-path input; a caller that requests strong
    validation can still hash every returned file.
    """

    result = ProjectScan()
    root = Path(project.path).resolve()
    with timed(result.metrics, "directory_traversal"):
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for directory in dirs:
                with timed(result.metrics, "path_check"):
                    excluded = (
                        _is_excluded_directory_name(directory, cfg)
                        or directory.casefold() in SENSITIVE_DIR_NAMES
                        or is_reparse_point(current_path / directory, result.metrics)
                    )
                if excluded:
                    result.skipped_dirs += 1
                    continue
                kept_dirs.append(directory)
            dirs[:] = kept_dirs

            for name in files:
                result.metrics.add_count("files_seen")
                path = current_path / name
                with timed(result.metrics, "path_check"):
                    try:
                        relative = path.relative_to(root).as_posix()
                        allowed, stat_result = _allowed_source_path_with_stat(root, relative, cfg, result.metrics, assume_walked=True)
                    except (OSError, ValueError):
                        result.skipped_files += 1
                        continue
                result.eligible_total += 1
                result.scanned_bytes += int(stat_result.st_size)
                if len(result.files) < cfg.limits.max_files_per_project:
                    result.files.append(ProjectFile(path=allowed, relative=relative, stat_result=stat_result))
                else:
                    if not result.truncated:
                        result.truncated = True
                        result.metrics.add_count("scan_limit_hits")
                    # Continue the stat/path pass to report the real project
                    # size, but do not retain or index files beyond the cap.
                    result.metrics.add_count("files_over_limit")
    over_limit = max(0, result.eligible_total - len(result.files))
    result.skipped_count = result.skipped_files + result.skipped_dirs + over_limit
    result.metrics.add_count("eligible_files", len(result.files))
    result.metrics.add_count("eligible_files_total", result.eligible_total)
    result.metrics.add_count("skipped_files", result.skipped_files)
    result.metrics.add_count("skipped_dirs", result.skipped_dirs)
    result.metrics.add_count("scanned_bytes", result.scanned_bytes)
    return result


def iter_project_files(project: ProjectRecord, cfg: AtlasConfig) -> Iterator[tuple[Path, str]]:
    scan = scan_project_files(project, cfg)
    for item in scan.files:
        yield item.path, item.relative

