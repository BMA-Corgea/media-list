"""Test isolation. Read this file top to bottom before writing a test.

``backend/config.py`` resolves ``config = load_config()`` at IMPORT TIME, and
``backend/main.py`` ends with ``app = create_app()`` at module scope, which calls
``bootstrap()`` — so the mere act of ``import backend.main`` creates/opens a database at
whatever path ``MEDIA_LIST_DB`` names. A fixture that swaps the path *after* that import has
already lost: it would have opened ``data/media-list.db``, the owner's real list.

So the environment override below runs before ANY ``backend.*`` import — including the ones
a few lines further down this same file. Do not reorder this file. Do not import ``backend``
anywhere above the marker.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# ── AC5: isolation, before backend exists to the interpreter ────────────────────────────
# One throwaway directory for the whole test session. `config` is a frozen singleton built
# once at import, so every test in this run shares this database file — per-test isolation
# comes from the `clean_db` autouse fixture below (DELETE, not a fresh file per test).
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="media-list-tests-"))
os.environ["MEDIA_LIST_DB"] = str(_TEST_DATA_DIR / "test.db")

# Real values are not needed and must not be trusted even if a real .env sits beside this
# repo (python-dotenv does not override an already-set variable — see config.py's own
# docstring — which is exactly the lever this uses). Fixed, obviously-fake values so
# `available()` is deterministic across machines: true whether or not the owner's real
# credentials happen to be sitting in a real .env when the suite runs.
os.environ.setdefault("TMDB_API_KEY", "test-tmdb-key")
os.environ.setdefault("IGDB_CLIENT_ID", "test-igdb-client-id")
os.environ.setdefault("IGDB_CLIENT_SECRET", "test-igdb-client-secret")
os.environ.setdefault("PEXELS_API_KEY", "test-pexels-key")
# Belt-and-suspenders: TestClient never binds a socket, but if anything ever did, it must
# not be able to collide with a real running instance on the default port.
os.environ.setdefault("MEDIA_LIST_HOST", "127.0.0.1")
os.environ.setdefault("MEDIA_LIST_PORT", "0")

# ── everything below this line may import backend ───────────────────────────────────────
import asyncio  # noqa: E402
from typing import Callable  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from backend.config import config  # noqa: E402
from backend.db import connection  # noqa: E402
from backend.main import app  # noqa: E402
from backend.sources import anilist, base, igdb, tmdb  # noqa: E402
from backend import artwork  # noqa: E402

# Fails the whole session at collection time, loudly, if the override above was somehow too
# late — better than a passing suite that silently wrote to the owner's database.
assert config.db_path == _TEST_DATA_DIR / "test.db", (
    f"MEDIA_LIST_DB isolation did not take effect: config.db_path is {config.db_path!r}. "
    "backend.config must have been imported before conftest set the environment variable."
)
assert "media-list-tests-" in str(config.db_path), config.db_path


# ── AC6: no network by default ───────────────────────────────────────────────────────────
# `config.py` calls `load_dotenv(REPO_ROOT / ".env")` at import — on the owner's machine
# real TMDB/AniList/IGDB keys are live inside this very process, so an un-stubbed call would
# genuinely reach the internet. Missing credentials are NOT the guard (a checkout without a
# .env would pass by accident and prove nothing); this is a POSITIVE guard: every source's
# `client()` is replaced with one built on an `httpx.MockTransport` whose only route raises.
#
# GOTCHA that shaped this fixture: `tmdb.py`, `igdb.py`, `anilist.py` and `artwork.py` each
# do `from .sources.base import client` (or `from .base import client`) — a *name binding*
# made at THEIR import time. Patching `backend.sources.base.client` alone does nothing to
# those four modules' own `client` names, which still point at the original function object.
# The seam has to be patched in every module that imported the name, not just where it was
# defined.
_NETWORK_MODULES = (base, tmdb, igdb, anilist, artwork)


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Autouse: every test gets this unless marked ``@pytest.mark.live``.

    Yields the list of attempted-request descriptions (empty if none were attempted) so a
    test can assert exactly how many outbound calls it caused, even when the calling code
    swallows the resulting exception (`anilist.enrich` and `artwork.cache` both do, by
    design — see their docstrings).
    """
    attempts: list[str] = []

    if request.node.get_closest_marker("live"):
        # Opt-in tests want the real client; they carry their own credential/skip guard.
        yield attempts
        return

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(f"{req.method} {req.url}")
        raise RuntimeError(
            f"blocked outbound request in test: {req.method} {req.url} — "
            "stub the response or mark the test @pytest.mark.live (T-13 AC6)"
        )

    def blocked_client(*_args, **_kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    for module in _NETWORK_MODULES:
        monkeypatch.setattr(module, "client", blocked_client)

    yield attempts


# ── shared fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_db() -> None:
    """A blank `titles` table before every test — real isolation despite the shared file.

    `config` is resolved once per process, so every test in the run shares one SQLite file
    under the tmp dir set up above. This is what makes each test start from nothing anyway,
    with predictable autoincrement ids (row 1 is always the first row a test inserts).
    """
    with connection() as conn:
        conn.execute("DELETE FROM titles")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'titles'")


@pytest.fixture
def client() -> TestClient:
    """A `starlette.testclient.TestClient` around the real app — no port, no process."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def run_async() -> Callable:
    """Drive a coroutine from a sync test without pytest-asyncio (not a dependency here)."""
    return asyncio.run


def insert_title(**overrides) -> int:
    """Write one row straight into `titles`, bypassing the API and every source.

    Several tests (queue arithmetic, CSV round-trip, import atomicity) care about database
    behaviour, not about what a real TMDB/IGDB response looks like — seeding rows directly
    keeps them fast, deterministic, and honestly free of any network dependency rather than
    merely stubbed. `source`/`source_id` must be unique together (the schema's own
    constraint, `idx_titles_source`) — callers that insert many rows should vary them.
    """
    import json as _json

    from backend.titles import now as _now

    fields = {
        "source": "tmdb",
        "source_id": "1",
        "imdb_id": None,
        "anilist_id": None,
        "title": "Test Title",
        "original_title": None,
        "year": 2020,
        "kind": "movie",
        "summary": None,
        "poster_path": None,
        "backdrop_path": None,
        "genres": "[]",
        "detail": "{}",
        "why": None,
        "status": "queued",
        "stars": None,
        "review": None,
        "queue_position": None,
        "added_at": _now(),
        "watched_at": None,
    }
    fields.update(overrides)
    if "genres" in overrides and not isinstance(overrides["genres"], str):
        fields["genres"] = _json.dumps(overrides["genres"])
    if "detail" in overrides and not isinstance(overrides["detail"], str):
        fields["detail"] = _json.dumps(overrides["detail"])

    columns = list(fields)
    placeholders = ",".join("?" for _ in columns)
    with connection() as conn:
        cursor = conn.execute(
            f"INSERT INTO titles ({','.join(columns)}) VALUES ({placeholders})",
            tuple(fields[c] for c in columns),
        )
        return cursor.lastrowid


@pytest.fixture
def seed() -> Callable[..., int]:
    """Fixture form of `insert_title`, for tests that prefer `seed(title=...)` over an import."""
    return insert_title


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.live (real TMDB/AniList/IGDB network calls, "
        "real credentials required) — skipped by default (T-13 AC6)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items) -> None:  # noqa: ANN001
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="live network test — run with `scripts/test.sh --live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)

