"""Configuration, resolved once from the environment.

Every path this app touches is derived here so nothing else has to guess where the
repository root is. `.env` is read if present; real environment variables win over it,
which is what makes `MEDIA_LIST_PORT=8000 ./start.sh` work without editing a file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


def _path(env_name: str, default: str) -> Path:
    """A path from the environment, relative paths resolved against the repo root."""
    raw = os.getenv(env_name, default)
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p)


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    db_path: Path
    #: Cached artwork and the IGDB token live here. Gitignored — its contents reveal the list.
    data_dir: Path
    art_dir: Path
    frontend_dist: Path

    tmdb_api_key: str | None
    pexels_api_key: str | None
    igdb_client_id: str | None
    igdb_client_secret: str | None


def load_config() -> Config:
    db_path = _path("MEDIA_LIST_DB", "data/media-list.db")
    data_dir = db_path.parent
    return Config(
        host=os.getenv("MEDIA_LIST_HOST", "127.0.0.1"),
        port=int(os.getenv("MEDIA_LIST_PORT", "7799")),
        db_path=db_path,
        data_dir=data_dir,
        art_dir=data_dir / "art",
        frontend_dist=REPO_ROOT / "frontend" / "dist",
        tmdb_api_key=os.getenv("TMDB_API_KEY") or None,
        pexels_api_key=os.getenv("PEXELS_API_KEY") or None,
        igdb_client_id=os.getenv("IGDB_CLIENT_ID") or None,
        igdb_client_secret=os.getenv("IGDB_CLIENT_SECRET") or None,
    )


config = load_config()
