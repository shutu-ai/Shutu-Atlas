from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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


def _optional_query(query: dict[str, list[str]], key: str) -> str | None:
    value = query.get(key, [None])[0]
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def create_gallery_server(
    cfg: AtlasConfig,
    host: str = "127.0.0.1",
    port: int = 8765,
    web_root: Path | None = None,
) -> ThreadingHTTPServer:
    """Build the read-only Gallery server without starting its loop."""

    store = IndexStore(cfg)
    gallery_web_root = (web_root or (cfg.project_root / "web")).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShutuAtlasGallery/0.2"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=True)
            try:
                if path == "/api/health":
                    _json(self, {"status": "ok", "gallery": "read-only", "store": store.status()})
                elif path == "/api/status":
                    _json(self, store.status())
                elif path == "/api/projects":
                    _json(self, {"status": "ok", "results": store.list_projects(_optional_query(query, "filter"), int(query.get("limit", [50])[0]))})
                elif path == "/api/search":
                    _json(
                        self,
                        store.search_code(
                            _optional_query(query, "q") or "",
                            int(query.get("limit", [20])[0]),
                            _optional_query(query, "project_id"),
                            _optional_query(query, "language"),
                        ),
                    )
                elif path == "/api/ui":
                    _json(
                        self,
                        store.find_ui(
                            _optional_query(query, "q") or "",
                            int(query.get("limit", [20])[0]),
                            _optional_query(query, "project_id"),
                        ),
                    )
                elif path.startswith("/api/ui/"):
                    _json(self, store.ui_detail(unquote(path.rsplit("/", 1)[-1])))
                elif path.startswith("/assets/"):
                    self._serve_asset(unquote(path.rsplit("/", 1)[-1]))
                else:
                    self._serve_web(path)
            except (ValueError, KeyError) as exc:
                _json(self, {"status": "invalid_request", "warnings": [str(exc)]}, 400)
            except Exception as exc:  # keep API errors truthful and structured
                _json(self, {"status": "error", "warnings": [f"{type(exc).__name__}: {exc}"]}, 500)

        def _serve_web(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
            target = (gallery_web_root / relative).resolve()
            if gallery_web_root not in target.parents and target != gallery_web_root:
                _json(self, {"status": "denied", "warnings": ["web path escapes root"]}, 403)
                return
            if not target.is_file():
                _json(self, {"status": "not_found", "warnings": ["gallery asset not found"]}, 404)
                return
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
            }
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
            content_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_types.get(target.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer((host, port), Handler)


def serve_gallery(cfg: AtlasConfig, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_gallery_server(cfg, host, port)
    print(f"Shutu-Atlas Gallery: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
