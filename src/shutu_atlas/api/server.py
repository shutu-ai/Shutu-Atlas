from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import AtlasConfig
from ..index.database import IndexStore


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def serve_gallery(cfg: AtlasConfig, host: str = "127.0.0.1", port: int = 8765) -> None:
    store = IndexStore(cfg)
    web_root = cfg.project_root / "web"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShutuAtlasGallery/0.2"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == "/api/health":
                    _json(self, {"status": "ok", "gallery": "read-only", "store": store.status()})
                elif path == "/api/status":
                    _json(self, store.status())
                elif path == "/api/projects":
                    _json(self, {"status": "ok", "results": store.list_projects(query.get("filter", [None])[0], int(query.get("limit", [50])[0]))})
                elif path == "/api/search":
                    _json(self, store.search_code(query.get("q", [""])[0], int(query.get("limit", [20])[0]), query.get("project_id", [None])[0], query.get("language", [None])[0]))
                elif path == "/api/ui":
                    _json(self, store.find_ui(query.get("q", [""])[0], int(query.get("limit", [20])[0]), query.get("project_id", [None])[0]))
                elif path.startswith("/api/ui/"):
                    _json(self, store.ui_detail(path.rsplit("/", 1)[-1]))
                elif path.startswith("/assets/"):
                    self._serve_asset(path.rsplit("/", 1)[-1])
                else:
                    self._serve_web(path)
            except (ValueError, KeyError) as exc:
                _json(self, {"status": "invalid_request", "warnings": [str(exc)]}, 400)
            except Exception as exc:  # keep API errors truthful and structured
                _json(self, {"status": "error", "warnings": [f"{type(exc).__name__}: {exc}"]}, 500)

        def _serve_web(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (web_root / relative).resolve()
            if web_root.resolve() not in target.parents and target != web_root.resolve():
                _json(self, {"status": "denied", "warnings": ["web path escapes root"]}, 403)
                return
            if not target.is_file():
                _json(self, {"status": "not_found", "warnings": ["gallery asset not found"]}, 404)
                return
            content_types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_types.get(target.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_asset(self, asset_id: str) -> None:
            detail = store.ui_detail(asset_id)
            asset = detail.get("asset")
            if not asset or asset.get("screenshot_status") != "available" or not asset.get("screenshot_path"):
                _json(self, {"status": "unavailable", "warnings": ["no real screenshot is indexed for this asset"]}, 404)
                return
            gallery_root = cfg.gallery_dir.resolve()
            target = (cfg.project_root / asset["screenshot_path"]).resolve()
            if gallery_root not in target.parents or not target.is_file():
                _json(self, {"status": "denied", "warnings": ["gallery path is invalid"]}, 403)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png" if target.suffix.lower() == ".png" else "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Shutu-Atlas Gallery: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

