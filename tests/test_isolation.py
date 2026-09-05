"""AC5 — the owner's data is never test input.

`conftest.py` does the actual work (setting `MEDIA_LIST_DB` before any `backend` import).
This file is the assertion that the mechanism actually took effect, kept separate from the
plumbing so a regression here fails with a normal test name and traceback instead of a
collection-time crash.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.config import config


def test_db_path_is_under_the_system_temp_dir() -> None:
    """Never the repo's own `data/media-list.db` — always a throwaway file elsewhere."""
    assert config.db_path.is_relative_to(Path(tempfile.gettempdir()))


def test_db_path_is_not_the_repo_default() -> None:
    from backend.config import REPO_ROOT

    owner_db = (REPO_ROOT / "data" / "media-list.db").resolve()
    assert config.db_path.resolve() != owner_db


def test_data_and_art_dirs_are_also_isolated() -> None:
    assert config.data_dir == config.db_path.parent
    assert config.art_dir == config.data_dir / "art"
    assert config.art_dir.is_relative_to(Path(tempfile.gettempdir()))


def test_database_file_actually_exists_here() -> None:
    """Bootstrap ran (at `backend.main` import) against the throwaway path, not skipped."""
    assert config.db_path.exists()
