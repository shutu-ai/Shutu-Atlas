from __future__ import annotations

import argparse
import importlib.util
import json
import platform
from pathlib import Path
import shutil
import sys

from . import __version__
from .api.server import serve_gallery
from .config import AtlasConfig, load_config
from .discovery import discover_projects
from .index.database import IndexStore
from .mcp_server.server import run_stdio
from .symbols.providers import FallbackProvider, SerenaProvider


def _config(args: argparse.Namespace) -> AtlasConfig:
    cfg = load_config(Path(args.config) if args.config else None)
    if getattr(args, "root", None):
        cfg.roots = [Path(args.root).expanduser().resolve()]
    if getattr(args, "include_project", None):
        cfg.include_projects = list(args.include_project)
    return cfg


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = _config(args)
    projects = discover_projects(cfg)
    _print({"status": "dry-run" if args.dry_run else "discovered", "source_roots": [str(p) for p in cfg.roots], "projects": [p.to_dict() for p in projects], "count": len(projects), "writes": []})
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    cfg = _config(args)
    projects = discover_projects(cfg)
    result = IndexStore(cfg).index(projects, changed_only=args.changed_only)
    result["source_roots"] = [str(p) for p in cfg.roots]
    result["discovered"] = len(projects)
    _print(result)
    return 0 if result["errors"] == 0 else 2


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _config(args)
    tools = {}
    for name in ("git", "rg", "uv", "node", "npm", "playwright", "serena", "codex", "opencode"):
        tools[name] = shutil.which(name)
    sdk = importlib.util.find_spec("mcp")
    payload = {"status": "ok", "version": __version__, "platform": platform.platform(), "python": sys.version.split()[0], "tools": tools, "python_mcp_sdk": bool(sdk), "sqlite_fts5": _fts5_available(), "config": {"project_root": str(cfg.project_root), "roots": [str(p) for p in cfg.roots], "db": str(cfg.db_path)}, "notes": []}
    if not tools["serena"]:
        payload["notes"].append("Serena unavailable: symbol search is DEGRADEd to static fallback")
    if not sdk:
        payload["notes"].append("official Python MCP SDK unavailable: compat stdio protocol remains available; SDK integration is BLOCKED_ENV")
    if not cfg.db_path.exists():
        payload["notes"].append("index database not initialized; run atlas index")
    _print(payload)
    return 0


def _fts5_available() -> bool:
    import sqlite3
    try:
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def _store_or_empty(cfg: AtlasConfig) -> IndexStore | None:
    if not cfg.db_path.exists():
        return None
    return IndexStore(cfg)


def cmd_list_projects(args: argparse.Namespace) -> int:
    store = _store_or_empty(_config(args))
    _print({"status": "ok", "results": store.list_projects(args.filter, args.limit) if store else [], "warnings": [] if store else ["index not initialized"]})
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    store = _store_or_empty(_config(args))
    _print(store.search_code(args.query, args.limit, args.project, args.language) if store else {"status": "unavailable", "results": [], "warnings": ["index not initialized"]})
    return 0 if store else 2


def cmd_capability(args: argparse.Namespace) -> int:
    store = _store_or_empty(_config(args))
    _print(store.find_capability(args.query, args.limit, args.project) if store else {"status": "unavailable", "results": [], "warnings": ["index not initialized"]})
    return 0 if store else 2


def cmd_symbol(args: argparse.Namespace) -> int:
    store = _store_or_empty(_config(args))
    if not store:
        _print({"status": "unavailable", "results": [], "warnings": ["index not initialized"]})
        return 2
    provider = SerenaProvider(_config(args), FallbackProvider(store))
    _print(provider.find_symbol(args.name, args.project, args.kind))
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    store = _store_or_empty(_config(args))
    _print(store.find_ui(args.query, args.limit, args.project) if store else {"status": "unavailable", "results": [], "warnings": ["index not initialized"]})
    return 0 if store else 2


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _config(args)
    store = _store_or_empty(cfg)
    if not store:
        _print({"status": "not_initialized", "db": str(cfg.db_path), "counts": {}})
        return 0
    result = store.status()
    result["serena"] = SerenaProvider(cfg, FallbackProvider(store)).health()
    _print(result)
    return 0


def cmd_gallery(args: argparse.Namespace) -> int:
    cfg = _config(args)
    if args.gallery_action == "import-screenshot":
        store = IndexStore(cfg)
        _print(store.import_screenshot(args.asset_id, Path(args.path).expanduser().resolve()))
        return 0
    serve_gallery(cfg, args.host, args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    if args.transport != "stdio":
        _print({"status": "unsupported", "warnings": ["Only stdio is enabled in v0.2.0"]})
        return 2
    run_stdio(_config(args))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atlas", description="Shutu-Atlas 本地只读跨项目代码与 UI 资产参考库")
    p.add_argument("--config", help="atlas.toml 路径")
    sub = p.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor"); doctor.set_defaults(func=cmd_doctor)
    scan = sub.add_parser("scan"); scan.add_argument("--root"); scan.add_argument("--dry-run", action="store_true"); scan.set_defaults(func=cmd_scan)
    index = sub.add_parser("index"); index.add_argument("--root"); index.add_argument("--changed-only", action="store_true"); index.add_argument("--include-project", action="append", default=[], help="只索引指定 project name 或 project_id，可重复"); index.set_defaults(func=cmd_index)
    ls = sub.add_parser("list-projects"); ls.add_argument("--filter"); ls.add_argument("--limit", type=int, default=50); ls.set_defaults(func=cmd_list_projects)
    search = sub.add_parser("search-code"); search.add_argument("query"); search.add_argument("--limit", type=int, default=10); search.add_argument("--project"); search.add_argument("--language"); search.set_defaults(func=cmd_search)
    cap = sub.add_parser("find-capability"); cap.add_argument("query"); cap.add_argument("--limit", type=int, default=10); cap.add_argument("--project"); cap.set_defaults(func=cmd_capability)
    symbol = sub.add_parser("find-symbol"); symbol.add_argument("name"); symbol.add_argument("--project"); symbol.add_argument("--kind"); symbol.set_defaults(func=cmd_symbol)
    ui = sub.add_parser("find-ui"); ui.add_argument("query", nargs="?", default="dashboard"); ui.add_argument("--limit", type=int, default=12); ui.add_argument("--project"); ui.set_defaults(func=cmd_ui)
    status = sub.add_parser("status"); status.set_defaults(func=cmd_status)
    gallery = sub.add_parser("gallery"); gallery.add_argument("gallery_action", nargs="?", choices=["serve", "import-screenshot"], default="serve"); gallery.add_argument("--host", default="127.0.0.1"); gallery.add_argument("--port", type=int, default=8765); gallery.add_argument("--asset-id"); gallery.add_argument("--path"); gallery.set_defaults(func=cmd_gallery)
    mcp = sub.add_parser("mcp"); mcp.add_argument("mcp_action", nargs="?", choices=["serve"], default="serve"); mcp.add_argument("--transport", default="stdio", choices=["stdio"]); mcp.set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "gallery" and args.gallery_action == "import-screenshot" and (not args.asset_id or not args.path):
        parser().error("gallery import-screenshot requires --asset-id and --path")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

