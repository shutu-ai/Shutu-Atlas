from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Iterator

from .config import AtlasConfig


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

    def to_dict(self) -> dict:
        return asdict(self)


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


def _git_info(path: Path, timeout: float) -> tuple[bool, str | None, str | None, bool | None]:
    top = _run_git(path, ["rev-parse", "--show-toplevel"], timeout)
    if not top:
        return False, None, None, None
    head = _run_git(path, ["rev-parse", "HEAD"], timeout)
    branch = _run_git(path, ["branch", "--show-current"], timeout)
    status = _run_git(path, ["status", "--porcelain", "--untracked-files=all"], timeout)
    return True, head, branch, bool(status)


def _project_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()[:16]


def is_reparse_point(path: Path) -> bool:
    """Return True for Windows junctions/symlinks without following them."""
    try:
        attrs = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & 0x400000) or path.is_symlink()
    except OSError:
        return True


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


def discover_projects(cfg: AtlasConfig) -> list[ProjectRecord]:
    found: dict[str, ProjectRecord] = {}

    def add_candidate(path: Path, kind: str, markers: list[str]) -> None:
        is_git, head, branch, dirty = _git_info(path, cfg.limits.command_timeout_seconds)
        languages, frameworks = _detect_stack(path, markers)
        record = ProjectRecord(
            project_id=_project_id(path), name=path.name, path=str(path.resolve()),
            is_git=is_git, git_head=head, branch=branch, dirty=dirty,
            languages=languages, frameworks=frameworks, markers=markers,
            discovery_kind=kind,
        )
        if cfg.include_projects and record.name not in cfg.include_projects and record.project_id not in cfg.include_projects:
            record.excluded, record.exclusion_reason = True, "not in include_projects"
        if record.name in cfg.exclude_projects or record.project_id in cfg.exclude_projects:
            record.excluded, record.exclusion_reason = True, "exclude_projects"
        found[record.project_id] = record

    for root in cfg.roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.is_dir() or is_reparse_point(path) or path.name.startswith(".") or path.name in cfg.excluded_dirs or path.resolve() == cfg.project_root:
                continue
            candidate, kind, markers = _is_candidate(path)
            if not candidate:
                continue
            direct_markers = [p.name for p in path.iterdir() if p.is_file() and p.name in MARKERS]
            if kind == "source" and not direct_markers:
                nested = []
                for child in path.iterdir():
                    if child.is_dir() and not is_reparse_point(child) and not child.name.startswith("."):
                        child_candidate, child_kind, child_markers = _is_candidate(child)
                        if child_candidate and (child_kind == "git" or child_markers):
                            nested.append((child, child_kind, child_markers))
                if nested:
                    for child, child_kind, child_markers in nested:
                        add_candidate(child, child_kind, child_markers)
                    continue
            add_candidate(path, kind, markers)
    return sorted(found.values(), key=lambda p: p.name.casefold())


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


def safe_source_path(project_root: Path, relative_path: str) -> Path:
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
        if current != base and is_reparse_point(current):
            raise ValueError("symlink source is not readable")
    target = raw_target.resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes project root")
    return target


def allowed_source_path(project_root: Path, relative_path: str, cfg: AtlasConfig) -> Path:
    """Return a path only when it belongs to the indexable file set.

    ``iter_project_files`` and all indexed source consumers call this helper so
    a file cannot be searchable or readable merely because ripgrep can see it.
    """

    relative = Path(relative_path)
    if any(part in cfg.excluded_dirs for part in relative.parts):
        raise ValueError("path is in an excluded directory")
    raw_target = project_root.resolve() / relative
    if is_sensitive(raw_target) or raw_target.suffix.lower() not in TEXT_EXTENSIONS:
        raise ValueError("path is not in the readable file set")
    target = safe_source_path(project_root, relative_path)
    if not target.is_file():
        raise ValueError("source file is not readable")
    try:
        if target.stat().st_size > cfg.limits.max_file_bytes:
            raise ValueError("source file exceeds the configured size limit")
    except OSError as exc:
        raise ValueError("source file is not readable") from exc
    return target


def iter_project_files(project: ProjectRecord, cfg: AtlasConfig) -> Iterator[tuple[Path, str]]:
    root = Path(project.path).resolve()
    count = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            d for d in dirs
            if d not in cfg.excluded_dirs
            and d.casefold() not in SENSITIVE_DIR_NAMES
            and not is_reparse_point(current_path / d)
        ]
        for name in files:
            path = current_path / name
            try:
                relative = path.relative_to(root).as_posix()
                allowed = allowed_source_path(root, relative, cfg)
            except (OSError, ValueError):
                continue
            yield allowed, relative
            count += 1
            if count >= cfg.limits.max_files_per_project:
                return

