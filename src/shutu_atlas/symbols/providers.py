from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Any, Protocol

from ..config import AtlasConfig
from ..discovery import ProjectRecord, iter_project_files
from ..index.database import IndexStore


class SymbolProvider(Protocol):
    def find_symbol(self, name: str, project_id: str | None = None, kind: str | None = None) -> dict[str, Any]: ...
    def health(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class MirrorResult:
    project_id: str
    fingerprint: str
    mirror_root: Path
    copied_files: int
    source_root: Path


class SerenaWorkspaceManager:
    """Creates a bounded Hub-owned mirror; never activates Serena in a source repo."""

    def __init__(self, cfg: AtlasConfig):
        self.cfg = cfg

    def mirror(self, project: ProjectRecord) -> MirrorResult:
        files = list(iter_project_files(project, self.cfg))
        fingerprint = hashlib.sha256((project.git_head or "") .encode("utf-8") + str(len(files)).encode("ascii")).hexdigest()[:16]
        target = self.cfg.serena_dir / project.project_id / fingerprint
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        source_root = Path(project.path).resolve()
        for source, relative in files:
            destination = (target / relative).resolve()
            if target.resolve() not in destination.parents and destination != target.resolve():
                raise ValueError("mirror path escape")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or destination.stat().st_size != source.stat().st_size:
                shutil.copy2(source, destination)
            copied += 1
        return MirrorResult(project.project_id, fingerprint, target, copied, source_root)


class FallbackProvider:
    def __init__(self, store: IndexStore):
        self.store = store

    def find_symbol(self, name: str, project_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
        return self.store.find_symbols(name, project_id, kind)

    def health(self) -> dict[str, Any]:
        return {"status": "DEGRADED", "provider": "fallback-static", "reason": "Serena executable is unavailable"}


class SerenaProvider:
    """Capability boundary for Serena.

    The adapter deliberately does not expose Serena's write-capable tools. When the
    executable is absent it returns a truthful BLOCKED_ENV/DEGRADED state.
    """

    def __init__(self, cfg: AtlasConfig, fallback: FallbackProvider):
        self.cfg = cfg
        self.fallback = fallback
        self.executable = shutil.which("serena")

    def health(self) -> dict[str, Any]:
        if not self.executable:
            return {"status": "BLOCKED_ENV", "provider": "serena", "available": False, "reason": "serena executable not found"}
        return {"status": "AVAILABLE_UNVERIFIED", "provider": "serena", "available": True, "executable": self.executable, "reason": "adapter is isolated; integration command still requires an opted-in environment test"}

    def find_symbol(self, name: str, project_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
        health = self.health()
        result = self.fallback.find_symbol(name, project_id, kind)
        result["serena_health"] = health
        result["warnings"] = list(result.get("warnings", [])) + ["Serena is not used to claim verified results" if health["status"] != "AVAILABLE_UNVERIFIED" else "Serena executable detected; no write-capable tool is exposed"]
        return result

