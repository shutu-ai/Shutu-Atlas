from __future__ import annotations

from pathlib import Path
import shutil

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

