from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from shutu_atlas.discovery import discover_projects
from shutu_atlas.index.database import IndexStore, connect, utc_now


def test_discovery_and_index_evidence(test_config):
    projects = discover_projects(test_config)
    assert {p.name for p in projects} >= {"fixture-python", "fixture-ts-vue", "fixture-secrets", "fixture-mcp"}
    result = IndexStore(test_config).index(projects)
    assert result["projects_seen"] == len(projects)
    store = IndexStore(test_config)
    code = store.search_code("recover_after_restart", 10)
    assert any(item["relative_path"].endswith("tasks.py") for item in code["results"])
    capability = store.find_capability("任务重启恢复")
    assert capability["results"]
    assert capability["results"][0]["status"] in {"verified", "inferred"}
    ui = store.find_ui("dashboard KPI")
    assert ui["results"]
    assert all(item["screenshot_status"] == "unavailable" for item in ui["results"])


def test_hub_capability_review_survives_incremental_refresh(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    project = next(item for item in projects if item.name == "fixture-python")
    review = store.confirm_capability(project.project_id, "task_recovery", "verified", note="Reviewed against the fixture evidence")
    assert review["status"] == "ok"
    assert store.find_capability("任务重启恢复", project_filter=project.project_id)["results"][0]["status"] == "verified"
    store.index(discover_projects(test_config), changed_only=True)
    reviewed = store.find_capability("任务重启恢复", project_filter=project.project_id)["results"]
    assert reviewed and reviewed[0]["status"] == "verified"


def test_sensitive_files_and_source_bounds(test_config):
    projects = discover_projects(test_config)
    IndexStore(test_config).index(projects)
    store = IndexStore(test_config)
    assert not store.search_code("ATLAS_TEST_SECRET", 10)["results"]
    row = store.search_code("public_function", 10)["results"]
    assert row
    denied = store.get_source(row[0]["project_id"], row[0]["file_id"], 1, 100)
    assert denied["status"] == "ok"
    assert "public_function" in denied["text"]
    assert store.get_source(row[0]["project_id"], 999999)["status"] == "not_found"


def test_allowed_file_set_is_shared_by_index_fts_rg_and_source_reads(test_config, fixture_root):
    projects = discover_projects(test_config)
    IndexStore(test_config).index(projects)
    store = IndexStore(test_config)

    for query in ("ATLAS_TEST_SECRET", "must-not-be-indexed", "PRIVATE_KEY_MUST_NOT_BE_INDEXED", "HIDDEN_SECRET_MUST_NOT_BE_INDEXED", "EXCLUDED_DIRECTORY_SECRET"):
        assert store.search_code(query, 20)["results"] == []

    public = store.search_code("public_function", 20)["results"]
    assert public and public[0]["relative_path"] == "safe.py"
    source = store.get_source(public[0]["project_id"], public[0]["file_id"])
    assert source["status"] == "ok" and "public_function" in source["text"]

    link = fixture_root / "fixture-secrets" / "linked-safe.py"
    try:
        os.symlink(fixture_root / "fixture-secrets" / "safe.py", link)
    except (OSError, NotImplementedError):
        pytest.skip("Windows symlink creation is unavailable in this environment")
    try:
        IndexStore(test_config).index(discover_projects(test_config), changed_only=True)
        assert store.search_code("public_function", 20)["results"]
        assert all(item["relative_path"] != "linked-safe.py" for item in store.search_code("public_function", 20)["results"])
    finally:
        link.unlink(missing_ok=True)


def test_empty_project_filter_means_all_projects(test_config):
    store = IndexStore(test_config)
    store.index(discover_projects(test_config))
    result = store.search_code("recover_after_restart", 20, project_id="")
    assert result["results"]


def test_incremental_change_and_remove(test_config, fixture_root):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    python_file = fixture_root / "fixture-python" / "app" / "tasks.py"
    python_file.write_text(python_file.read_text(encoding="utf-8") + "\n\ndef new_incremental_symbol():\n    return True\n", encoding="utf-8")
    changed = store.index(discover_projects(test_config), changed_only=True)
    assert changed["files_indexed"] >= 1
    assert store.search_code("new_incremental_symbol")["results"]
    python_file.unlink()
    store.index(discover_projects(test_config), changed_only=True)
    assert not store.search_code("new_incremental_symbol")["results"]


def test_manual_verification_expires_when_evidence_changes(test_config, fixture_root):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    project = next(item for item in projects if item.name == "fixture-python")
    store.confirm_capability(project.project_id, "task_recovery", "verified", note="reviewed")
    assert store.find_capability("任务重启恢复", project_filter=project.project_id)["results"][0]["status"] == "verified"

    source = fixture_root / "fixture-python" / "app" / "tasks.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# evidence changed after human review\n", encoding="utf-8")
    store.index(discover_projects(test_config), changed_only=True)
    result = store.find_capability("任务重启恢复", project_filter=project.project_id)["results"][0]
    assert result["status"] == "expired"
    assert result["verification_expired"] is True
    assert result["manual_status"] == "verified"


def test_ui_asset_identity_and_screenshot_survive_full_and_incremental_refresh(test_config, fixture_root):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    assets = [item for item in store.find_ui("dashboard", 20)["results"] if item["relative_path"] == "src/Dashboard.vue"]
    assert len(assets) == 2
    assert len({item["asset_id"] for item in assets}) == 2

    screenshot = test_config.gallery_dir.parent / "dashboard-test.png"
    screenshot.write_bytes(b"not-a-real-image-but-a-real-imported-file")
    try:
        imported = store.import_screenshot(assets[0]["asset_id"], screenshot)
        assert imported["status"] == "ok"

        store.index(discover_projects(test_config), changed_only=False)
        assert store.ui_detail(assets[0]["asset_id"])["asset"]["screenshot_status"] == "available"

        one_dashboard = fixture_root / "fixture-multi-repo" / "one" / "src" / "Dashboard.vue"
        one_dashboard.write_text(one_dashboard.read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")
        store.index(discover_projects(test_config), changed_only=True)
        detail = store.ui_detail(assets[0]["asset_id"])
        assert detail["asset"]["screenshot_status"] == "available"
    finally:
        screenshot.unlink(missing_ok=True)


def test_legacy_ui_asset_id_migration_preserves_alias_and_screenshot(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    asset = store.find_ui("dashboard", 20)["results"][0]
    canonical_id = asset["asset_id"]
    legacy_id = "legacy-path-only-id"
    screenshot = test_config.gallery_dir.parent / "legacy-test.png"
    screenshot.write_bytes(b"legacy screenshot")
    try:
        store.import_screenshot(canonical_id, screenshot)
        with connect(test_config.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("UPDATE schema_meta SET value='3' WHERE key='schema_version'")
            conn.execute("UPDATE ui_assets SET asset_id=? WHERE asset_id=?", (legacy_id, canonical_id))
            conn.execute("UPDATE ui_source_links SET asset_id=? WHERE asset_id=?", (legacy_id, canonical_id))
            conn.commit()

        migrated = IndexStore(test_config)
        detail = migrated.ui_detail(legacy_id)
        assert detail["status"] == "ok"
        assert detail["asset"]["asset_id"] != legacy_id
        assert detail["asset"]["screenshot_status"] == "available"
        assert migrated.ui_detail(detail["asset"]["asset_id"])["asset"]["asset_id"] == detail["asset"]["asset_id"]
    finally:
        screenshot.unlink(missing_ok=True)


def test_suggest_reuse_returns_evidence_and_adaptation_fields(test_config):
    store = IndexStore(test_config)
    store.index(discover_projects(test_config))
    result = store.suggest_reuse("dashboard KPI", "Vue 3 + TypeScript", 3)
    assert result["candidates"] or result["ui_candidates"]
    candidate = (result["candidates"] or result["ui_candidates"])[0]
    assert candidate["candidate_stack"]
    assert "dependency_clues" in candidate
    assert candidate["evidence_source"]["relative_path"]
    assert candidate["adaptation_risk"] in {"low", "medium", "high", "unknown"}
    assert candidate["reuse_type"] in {"reuse_direct", "adapt", "visual_reference", "not_recommended", "unknown"}


def test_abandoned_index_run_is_recovered(test_config):
    store = IndexStore(test_config)
    with connect(test_config.db_path) as conn:
        conn.execute(
            "INSERT INTO index_runs(started_at,mode,status,owner_pid) VALUES(?,?,?,?)",
            (utc_now(), "changed-only", "running", None),
        )
        conn.commit()

    recovered = IndexStore(test_config)
    status = recovered.status()
    assert status["last_index"]["status"] == "interrupted"


def test_removed_project_is_pruned_on_root_refresh(test_config, fixture_root):
    store = IndexStore(test_config)
    store.index(discover_projects(test_config))
    removed = next(project for project in discover_projects(test_config) if project.name == "fixture-secrets")
    shutil.rmtree(fixture_root / "fixture-secrets")
    store.index(discover_projects(test_config), changed_only=True)
    assert not any(item["project_id"] == removed.project_id for item in store.list_projects(limit=50))

