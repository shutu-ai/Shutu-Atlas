from __future__ import annotations

from dataclasses import dataclass
import ast
import hashlib
import asyncio
import json
import os
from pathlib import Path
import shutil
import threading
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
        digests: dict[str, str] = {}
        fingerprint_hasher = hashlib.sha256((project.git_head or "").encode("utf-8"))
        for source, relative in files:
            digest = _file_digest(source)
            digests[relative] = digest
            fingerprint_hasher.update(relative.encode("utf-8"))
            fingerprint_hasher.update(digest.encode("ascii"))
        fingerprint = fingerprint_hasher.hexdigest()[:16]
        target = self.cfg.serena_dir / project.project_id / fingerprint
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        source_root = Path(project.path).resolve()
        for source, relative in files:
            destination = (target / relative).resolve()
            if target.resolve() not in destination.parents and destination != target.resolve():
                raise ValueError("mirror path escape")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or _file_digest(destination) != digests[relative]:
                shutil.copy2(source, destination)
            copied += 1
        return MirrorResult(project.project_id, fingerprint, target, copied, source_root)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        if not _mcp_client_available():
            return {"status": "BLOCKED_ENV", "provider": "serena", "available": False, "executable": self.executable, "reason": "official MCP Python SDK is unavailable"}
        return {"status": "AVAILABLE_UNVERIFIED", "provider": "serena", "available": True, "executable": self.executable, "reason": "isolated Serena stdio adapter is ready for an opted-in integration call"}

    def find_symbol(self, name: str, project_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
        health = self.health()
        if health["status"] == "AVAILABLE_UNVERIFIED" and project_id:
            try:
                result = self._find_symbol_with_serena(name, project_id, kind)
                if result is not None:
                    return result
            except Exception as exc:
                health = {**health, "status": "DEGRADED", "reason": f"Serena query failed: {type(exc).__name__}: {exc}"}
        result = self.fallback.find_symbol(name, project_id, kind)
        result["serena_health"] = health
        result["warnings"] = list(result.get("warnings", [])) + [
            "Serena is not used to claim verified results" if health["status"] != "AVAILABLE_UNVERIFIED" else "Serena query was not run; no write-capable tool is exposed"
        ]
        return result

    def _find_symbol_with_serena(self, name: str, project_id: str, kind: str | None) -> dict[str, Any] | None:
        project = self.fallback.store.get_project(project_id)
        if not project:
            return None
        record = _project_record(project)
        mirror = SerenaWorkspaceManager(self.cfg).mirror(record)
        symbols, references = _run_async(lambda: self._query_serena(mirror.mirror_root, name))
        mapped = _map_serena_symbols(symbols, record, references)
        if kind:
            mapped = [item for item in mapped if item.get("kind", "").lower() == kind.lower()]
        return {
            "status": "ok",
            "source": "serena",
            "results": mapped[: self.cfg.limits.max_results],
            "serena_health": {"status": "PASS", "provider": "serena", "available": True, "executable": self.executable, "mirror": str(mirror.mirror_root)},
            "warnings": ["Serena ran only against a Hub-owned mirror; source files remain read-only"],
        }

    async def _query_serena(self, mirror_root: Path, name: str) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        from mcp import Client, StdioServerParameters

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SERENA_HOME": str((self.cfg.serena_dir / "_home").resolve()),
            "SERENA_USAGE_REPORTING": "false",
            # Keep Serena/uv bootstrap state inside the Hub-owned working area.
            "UV_CACHE_DIR": str((self.cfg.serena_dir / "_uv-cache").resolve()),
        }
        Path(env["SERENA_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(env["UV_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
        tool_timeout = max(30.0, self.cfg.limits.command_timeout_seconds)
        server = StdioServerParameters(
            command=self.executable,
            # Serena defaults to its REPL interface in the installed runtime.  Request the
            # official one-tool-per-operation interface so symbolic read tools are available;
            # this adapter calls only find_symbol/find_referencing_symbols below.
            args=[
                "start-mcp-server",
                "--project",
                str(mirror_root),
                "--context",
                "codex",
                "--agent-interface",
                "tools",
                "--tool-timeout",
                str(tool_timeout),
                "--open-web-dashboard",
                "false",
            ],
            env=env,
        )
        async with Client(server, read_timeout_seconds=tool_timeout) as client:
            tools = await client.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            find_name = "find_symbol" if "find_symbol" in tool_names else next((n for n in tool_names if n.endswith("find_symbol")), None)
            if not find_name:
                raise RuntimeError("Serena find_symbol tool is not exposed by the selected context")
            result = await client.call_tool(find_name, {"name_path_pattern": name, "include_body": False, "max_answer_chars": self.cfg.limits.max_chars})
            symbols = _serena_payload(result)
            references: dict[str, list[dict[str, Any]]] = {}
            ref_name = "find_referencing_symbols" if "find_referencing_symbols" in tool_names else next((n for n in tool_names if n.endswith("find_referencing_symbols")), None)
            if ref_name:
                for symbol in symbols[:3]:
                    name_path = symbol.get("name_path")
                    relative_path = symbol.get("relative_path")
                    if not name_path:
                        continue
                    args = {"name_path": name_path}
                    if relative_path:
                        args["relative_path"] = relative_path
                    references[name_path] = _serena_payload(await client.call_tool(ref_name, args))
            return symbols, references


def _mcp_client_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


def _run_async(factory):
    """Bridge the sync provider API to async MCP clients safely.

    The compatibility stdio transport calls providers without an event loop;
    the official MCP SDK invokes them from one.  A worker thread keeps the
    synchronous public API while avoiding nested ``asyncio.run`` calls.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list[Any] = []
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as exc:  # re-raise in the caller's context
            error.append(exc)

    thread = threading.Thread(target=worker, name="shutu-atlas-async-bridge", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def _project_record(project: dict[str, Any]) -> ProjectRecord:
    return ProjectRecord(
        project_id=project["project_id"],
        name=project["name"],
        path=project["path"],
        is_git=bool(project.get("is_git")),
        git_head=project.get("git_head"),
        branch=project.get("branch"),
        dirty=project.get("dirty"),
        languages=list(project.get("languages", [])),
        frameworks=list(project.get("frameworks", [])),
        markers=list(project.get("markers", [])),
        discovery_kind=project.get("discovery_kind", "indexed"),
    )


def _serena_payload(result: Any) -> list[dict[str, Any]]:
    raw = getattr(result, "structured_content", None)
    if raw is None:
        texts = [getattr(block, "text", "") for block in getattr(result, "content", [])]
        raw = next((text for text in texts if text), "")
    if isinstance(raw, dict):
        for key in ("symbols", "results", "result"):
            if key in raw:
                raw = raw[key]
                break
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            # Serena 2.1.0 renders symbolic results as a Python-literal string
            # (single-quoted dicts) through MCP, while older versions returned JSON.
            try:
                raw = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                return []
    if isinstance(raw, dict):
        raw = [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _map_serena_symbols(symbols: list[dict[str, Any]], project: ProjectRecord, references: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    source_root = Path(project.path).resolve()
    mapped: list[dict[str, Any]] = []
    for symbol in symbols:
        relative = str(symbol.get("relative_path", "")).replace("/", "\\")
        source_path = (source_root / relative).resolve()
        if not relative or (source_path != source_root and source_root not in source_path.parents):
            continue
        location = symbol.get("body_location") or symbol.get("location") or {}
        name_path = str(symbol.get("name_path") or symbol.get("name") or "")
        mapped.append({
            "name": name_path.rsplit("/", 1)[-1],
            "name_path": name_path,
            "kind": symbol.get("kind") or symbol.get("type") or "symbol",
            "relative_path": relative,
            "path": str(source_path),
            "start_line": int(location.get("start_line", 1)),
            "end_line": int(location.get("end_line", location.get("start_line", 1))),
            "source": "serena",
            "match_reason": "serena_reference",
            "confidence": "verified",
            "references": references.get(name_path, []),
        })
    return mapped

