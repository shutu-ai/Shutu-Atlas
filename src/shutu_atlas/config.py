from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib


DEFAULT_EXCLUDED_DIRS = {
    ".git", ".local", ".venv", "venv", "node_modules", "dist", "build",
    "coverage", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".next", ".cache", ".pnpm-store", ".yarn", ".gradle", ".idea", ".vscode", ".turbo",
    ".parcel-cache", ".codex", ".opencode", ".serena", ".agent", ".agents", "target", "bin", "obj", "vendor", "tmp", "temp", "cache", "logs", "out",
    ".codegraph", ".go-cache", ".go-mod-cache", ".deploy-staging", "pytest-cache-files",
}


@dataclass(slots=True)
class Limits:
    max_file_bytes: int = 512_000
    max_files_per_project: int = 20_000
    max_results: int = 50
    max_snippet_lines: int = 12
    max_chars: int = 8_000
    command_timeout_seconds: float = 8.0
    changed_only_hash_mode: str = "stat"
    freshness_stale_after_hours: float = 26.0


@dataclass(slots=True)
class AtlasConfig:
    project_root: Path
    roots: list[Path]
    db_path: Path
    gallery_dir: Path
    serena_dir: Path
    include_projects: list[str] = field(default_factory=list)
    exclude_projects: list[str] = field(default_factory=list)
    excluded_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_DIRS))
    limits: Limits = field(default_factory=Limits)

    def normalized(self) -> "AtlasConfig":
        self.project_root = self.project_root.resolve()
        self.roots = [p.expanduser().resolve() for p in self.roots]
        self.db_path = self.db_path.expanduser().resolve()
        self.gallery_dir = self.gallery_dir.expanduser().resolve()
        self.serena_dir = self.serena_dir.expanduser().resolve()
        return self

    def ensure_local_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.gallery_dir.mkdir(parents=True, exist_ok=True)
        self.serena_dir.mkdir(parents=True, exist_ok=True)


def _path(value: str | os.PathLike[str], base: Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else base / p


def default_config(project_root: Path | None = None) -> AtlasConfig:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    source_root = root.parent
    return AtlasConfig(
        project_root=root,
        roots=[source_root],
        db_path=root / ".local" / "atlas.sqlite3",
        gallery_dir=root / ".local" / "gallery",
        serena_dir=root / ".local" / "serena-workspaces",
    ).normalized()


def load_config(path: Path | None = None, project_root: Path | None = None) -> AtlasConfig:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    config_path = path or (root / "atlas.toml")
    if not config_path.exists():
        return default_config(root)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    scan = data.get("scan", {})
    limits_data = data.get("limits", {})
    roots = [_path(v, root) for v in scan.get("roots", [str(root.parent)])]
    limits = Limits(**{k: v for k, v in limits_data.items() if k in Limits.__dataclass_fields__})
    cfg = AtlasConfig(
        project_root=root,
        roots=roots,
        db_path=_path(paths.get("db", ".local/atlas.sqlite3"), root),
        gallery_dir=_path(paths.get("gallery", ".local/gallery"), root),
        serena_dir=_path(paths.get("serena_workspaces", ".local/serena-workspaces"), root),
        include_projects=list(scan.get("include_projects", [])),
        exclude_projects=list(scan.get("exclude_projects", [])),
        excluded_dirs=set(DEFAULT_EXCLUDED_DIRS) | set(scan.get("excluded_dirs", [])),
        limits=limits,
    )
    return cfg.normalized()

