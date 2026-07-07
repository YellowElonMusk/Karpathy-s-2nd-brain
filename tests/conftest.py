import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def repo_copy(tmp_path: Path) -> Path:
    """A mutable copy of the real repo's knowledge/ + templates/."""
    shutil.copytree(REPO_ROOT / "knowledge", tmp_path / "knowledge")
    shutil.copytree(REPO_ROOT / "templates", tmp_path / "templates")
    return tmp_path


@pytest.fixture(scope="session")
def real_root() -> Path:
    return REPO_ROOT
