from __future__ import annotations

import sys
from pathlib import Path
import shutil
import uuid

import pytest

from shutu_atlas.config import AtlasConfig


# Optional integrations are kept out of the base install.  When a local
# verification run places them in the ignored Hub cache, make them visible to
# pytest without changing the user's Python environment.
_optional_deps = Path(__file__).parents[1] / ".local" / "python-deps"
if _optional_deps.is_dir():
    sys.path.insert(0, str(_optional_deps))


@pytest.fixture
def fixture_root() -> Path:
    source = Path(__file__).parent / "fixtures"
    root = Path(__file__).parent / ".test-work" / uuid.uuid4().hex / "sources"
    root.mkdir(parents=True)
    for name in ("fixture-python", "fixture-ts-vue", "fixture-secrets", "fixture-multi-repo", "fixture-mcp"):
        shutil.copytree(source / name, root / name)
    # These are disposable test copies, never source projects.
    return root


@pytest.fixture
def test_config(fixture_root: Path) -> AtlasConfig:
    hub = fixture_root.parent.parent / "hub"
    return AtlasConfig(
        project_root=hub,
        roots=[fixture_root],
        db_path=hub / ".local" / "atlas.sqlite3",
        gallery_dir=hub / ".local" / "gallery",
        serena_dir=hub / ".local" / "serena-workspaces",
    ).normalized()
