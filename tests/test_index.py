from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from shutu_atlas.discovery import _is_excluded_directory_name, discover_projects
from shutu_atlas.index import database as database_module
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


def test_generated_directory_prefixes_are_excluded(test_config):
    for name in (".deploy-staging", ".deploy-staging-20261023", ".deploy-staging-temp", "pytest-cache-files-a0ot86lp"):
        assert _is_excluded_directory_name(name, test_config)


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


def test_rename_is_reconciled_by_incremental_refresh(test_config, fixture_root):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    source = fixture_root / "fixture-python" / "app" / "tasks.py"
    renamed = source.with_name("tasks_renamed.py")
    source.rename(renamed)
    try:
        result = store.index(discover_projects(test_config), changed_only=True)
        assert result["changed_files"] >= 1
        matches = store.search_code("recover_after_restart", 20)["results"]
        assert any(item["relative_path"] == "app/tasks_renamed.py" for item in matches)
        assert all(item["relative_path"] != "app/tasks.py" for item in matches)
    finally:
        renamed.rename(source)


def test_stat_fast_path_and_force_hash_difference(test_config, fixture_root, monkeypatch):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    store.index(projects)
    source = fixture_root / "fixture-python" / "app" / "tasks.py"
    original_bytes = source.read_bytes()
    original_stat = source.stat()
    calls: list[Path] = []
    original_hash = database_module._sha256

    def tracked_hash(path: Path, metrics=None):
        calls.append(path)
        return original_hash(path, metrics)

    monkeypatch.setattr(database_module, "_sha256", tracked_hash)
    try:
        source.write_bytes(original_bytes.replace(b"recover_after_restart", b"restore_after_restart"))
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        ordinary = store.index(discover_projects(test_config), changed_only=True)
        assert ordinary["hash_mode"] == "stat"
        assert ordinary["changed_files"] == 0
        assert calls == []
        with database_module.connect(test_config.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT content FROM fts_content WHERE relative_path='app/tasks.py'"
            ).fetchone()
            assert row is not None
            assert "recover_after_restart" in row["content"]
            assert "restore_after_restart" not in row["content"]

        strong = store.index(discover_projects(test_config), changed_only=True, force_hash=True)
        assert strong["hash_mode"] == "force-hash"
        assert calls
        assert strong["changed_files"] >= 1
        with database_module.connect(test_config.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT content FROM fts_content WHERE relative_path='app/tasks.py'"
            ).fetchone()
            assert row is not None
            assert "restore_after_restart" in row["content"]
    finally:
        source.write_bytes(original_bytes)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))


def test_index_metrics_record_each_project_and_stage(test_config):
    projects = discover_projects(test_config)
    result = IndexStore(test_config).index(projects)
    assert result["projects_total"] == result["projects_completed"] == len(projects)
    assert result["stage_timings_ms"]["total"] >= 0
    assert {"directory_traversal", "path_check", "stat", "sha256", "sqlite_write", "fts_write"} <= set(result["stage_timings_ms"])
    for item in result["projects"]:
        assert item["file_count"] >= 0
        assert item["scanned_bytes"] >= 0
        assert item["elapsed_ms"] >= 0
        assert "path_check" in item["stage_timings_ms"]


def test_project_checkpoint_resume_after_interrupt(test_config, monkeypatch):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    original = store._index_project
    interrupt_name = projects[1].name

    def interrupt_once(conn, project, *args, **kwargs):
        if project.name == interrupt_name:
            raise KeyboardInterrupt()
        return original(conn, project, *args, **kwargs)

    monkeypatch.setattr(store, "_index_project", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        store.index(projects, changed_only=True)

    interrupted = IndexStore(test_config).status()
    assert interrupted["last_index"]["status"] == "interrupted"
    assert any(item["status"] == "ok" for item in interrupted["project_progress"])
    assert any(item["status"] == "interrupted" for item in interrupted["project_progress"])

    resumed = IndexStore(test_config).index(projects, changed_only=True, resume=True)
    assert resumed["status"] == "ok"
    assert resumed["resume_from_run"] is not None
    assert any(item["status"] == "resumed" for item in resumed["projects"])


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


def test_status_distinguishes_root_freshness_from_targeted_retry(test_config):
    projects = discover_projects(test_config)
    store = IndexStore(test_config)
    root_result = store.index(projects, changed_only=True, resume=True)
    assert root_result["status"] == "ok"
    status_after_root = IndexStore(test_config).status()
    assert root_result["coverage_scope"] == "root"
    assert status_after_root["last_successful_index_at"]
    assert status_after_root["freshness_level"] == "fresh"
    assert status_after_root["age_seconds"] >= 0
    assert status_after_root["last_attempt_status"] == "ok"

    retry = IndexStore(test_config).index(
        projects,
        changed_only=True,
        retry_projects=[projects[0].project_id],
    )
    assert retry["status"] == "ok"
    assert retry["coverage_scope"] == "targeted-retry"
    status_after_retry = IndexStore(test_config).status()
    assert status_after_retry["last_index"]["coverage_scope"] == "targeted-retry"
    assert status_after_retry["last_successful_index_at"] == status_after_root["last_successful_index_at"]
    assert status_after_retry["freshness"]["coverage_scope"] == "root"


def test_index_writer_lock_skips_parallel_entry_point(test_config):
    projects = discover_projects(test_config)
    with database_module.index_writer_lock(test_config.db_path):
        result = IndexStore(test_config).index(projects, changed_only=True, resume=True)
    assert result["status"] == "skipped_running"
    assert result["skip_reason"]

