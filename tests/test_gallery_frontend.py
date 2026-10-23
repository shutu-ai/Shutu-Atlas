from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import threading
from urllib.request import urlopen

import pytest

from shutu_atlas.api.server import create_gallery_server
from shutu_atlas.discovery import discover_projects
from shutu_atlas.index.database import IndexStore


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _prepare_gallery(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    assets = store.find_ui("dashboard", 20)["results"]
    assert assets
    asset = assets[0]
    screenshot = test_config.gallery_dir.parent / "gallery-test.png"
    screenshot.write_bytes(_ONE_PIXEL_PNG)
    assert store.import_screenshot(asset["asset_id"], screenshot)["status"] == "ok"
    repo_root = Path(__file__).parents[1]
    server = create_gallery_server(test_config, host="127.0.0.1", port=0, web_root=repo_root / "web")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return store, asset, screenshot, server, thread


def _cleanup_gallery(screenshot, server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    screenshot.unlink(missing_ok=True)


def test_gallery_api_screenshot_preview_and_all_project_code_search(test_config):
    _, asset, screenshot, server, thread = _prepare_gallery(test_config)
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/assets/{asset['asset_id']}") as response:
            assert response.headers["Content-Type"] == "image/png"
            assert response.read() == _ONE_PIXEL_PNG
        with urlopen(f"http://127.0.0.1:{port}/api/search?q=recover_after_restart&project_id=") as response:
            assert json.loads(response.read())["results"]
    finally:
        _cleanup_gallery(screenshot, server, thread)

def test_gallery_browser_interactions(test_config):
    if os.environ.get("SHUTU_ATLAS_BROWSER_E2E") != "1":
        pytest.skip("browser E2E requires explicit opt-in: SHUTU_ATLAS_BROWSER_E2E=1")
    sync_api = pytest.importorskip("playwright.sync_api")
    _, asset, screenshot, server, thread = _prepare_gallery(test_config)
    try:
        port = server.server_address[1]
        try:
            playwright = sync_api.sync_playwright().start()
        except Exception as exc:  # Windows named-pipe policy can block Playwright.
            pytest.skip(f"Playwright runtime unavailable: {exc}")
        try:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:  # browser binaries are an environment dependency.
                pytest.skip(f"Playwright Chromium unavailable: {exc}")
            page = browser.new_page()
            page.add_init_script(
                """Object.defineProperty(navigator, 'clipboard', {
                    value: {writeText: async (text) => { window.__copiedPrompt = text; }}, configurable: true
                });"""
            )
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.locator("#results .card").first.wait_for()
            assert page.locator(".thumb img").count() >= 1

            page.locator(".thumb img").first.locator("xpath=ancestor::article").locator("[data-detail]").click()
            page.locator("#detail[open]").wait_for()
            assert page.locator("#detail .detail-image").count() == 1
            page.locator("#copyPrompt").click()
            page.locator("#copyPrompt[data-copied='true']").wait_for()
            assert page.evaluate("window.__copiedPrompt").startswith("参考 UI 资产")
            page.locator("#close").click()

            page.locator("#query").fill("recover_after_restart")
            page.locator("#project").select_option("")
            page.locator("#code").click()
            page.locator("#results .card").first.wait_for()
            assert page.locator("#results .card").count() >= 1
            browser.close()
        finally:
            playwright.stop()
    finally:
        _cleanup_gallery(screenshot, server, thread)
