from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import pytest

from shutu_atlas.config import AtlasConfig


@pytest.fixture
def fixture_root() -> Path:
    source = Path(__file__).parent / "fixtures"
    root = Path(__file__).parent / ".test-work" / uuid.uuid4().hex / "sources"
    root.mkdir(parents=True)
    for name in ("fixture-python", "fixture-ts-vue", "fixture-secrets", "fixture-multi-repo"):
        shutil.copytree(source / name, root / name)
    # These are disposable test copies, never source projects.
    return root


@pytest.fixture
def test_config(fixture_root: Path) -> AtlasConfig:
    hub = fixture_root.parent.parent / "hub"
    return AtlasConfig(project_root=hub, roots=[fixture_root], db_path=hub / ".local" / "atlas.sqlite3", gallery_dir=hub / ".local" / "gallery", serena_dir=hub / ".local" / "serena-workspaces").normalized()

