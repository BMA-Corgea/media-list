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

# ── AC3 / AC4: the frontend must exist BEFORE backend.main is imported ──────────────────
# `create_app()` (called at `backend.main` import, same as bootstrap() above) only mounts
# the SPA catch-all route `if dist.is_dir()`. That check runs exactly once, at import — a
# frontend built AFTER this file's `from backend.main import app` below would be too late
# for the same reason a tmp MEDIA_LIST_DB set too late would be: the decision already got
# made. So the traversal-containment test (AC3) and the bundle-content test (AC4) both need
# `frontend/dist` to exist before the marker a few lines down.
#
# Mirrors `start.sh`'s own "build once if missing" logic exactly, so a first-time
# `scripts/test.sh` run behaves like a first-time `./start.sh` run. If npm is unavailable or
# the build fails, dependent tests skip with this reason rather than the whole suite dying —
# the ~50 tests that do not touch the frontend are still worth running.
import shutil  # noqa: E402
import subprocess  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"
_FRONTEND_DIST = _FRONTEND_DIR / "dist"
FRONTEND_UNAVAILABLE_REASON: str | None = None

def _frontend_is_stale() -> bool:
    """True if `dist` is missing OR older than the sources that produce it.

    "Build once if missing" was not enough. Merging T-17 into a checkout that already had a
    `dist` left the bundle SIX commits behind the source: `dist/` is gitignored, so a merge
    never updates it, and nothing here noticed. T-13's bundle-marker test caught it loudly —
    two failures naming the exact modules — but the browser suite then spent 9.5 minutes
    driving a stale app before failing. The guard worked; the harness lied to it.
    """
    if not _FRONTEND_DIST.is_dir():
        return True
    built = max((f.stat().st_mtime for f in _FRONTEND_DIST.rglob("*") if f.is_file()), default=0)
    sources = [_FRONTEND_DIR / "index.html", _FRONTEND_DIR / "vite.config.js",
               _FRONTEND_DIR / "package.json", *(_FRONTEND_DIR / "src").rglob("*")]
    newest = max((f.stat().st_mtime for f in sources if f.is_file()), default=0)
    return newest > built


if _frontend_is_stale():
    if shutil.which("npm") is None:
        FRONTEND_UNAVAILABLE_REASON = "npm not found on PATH — cannot build frontend/dist"
    else:
        try:
            subprocess.run(
                ["npm", "install", "--silent"], cwd=_FRONTEND_DIR,
                check=True, capture_output=True, text=True, timeout=300,
            )
            subprocess.run(
                ["npm", "run", "build", "--silent"], cwd=_FRONTEND_DIR,
                check=True, capture_output=True, text=True, timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = getattr(error, "stderr", "") or str(error)
            FRONTEND_UNAVAILABLE_REASON = f"frontend build failed: {detail[-500:]}"

if not _FRONTEND_DIST.is_dir() and FRONTEND_UNAVAILABLE_REASON is None:
    FRONTEND_UNAVAILABLE_REASON = "frontend/dist missing for an unknown reason"

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

# `fake_source` lives in tests/factories.py, shared across test modules this way rather than
# duplicated per file or piled into this already-load-bearing conftest.
pytest_plugins = ["tests.factories"]


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


@pytest.fixture(scope="session")
def frontend_dist() -> Path:
    """The built frontend, guaranteed to exist by this point — skip instead of failing.

    Building already happened at the top of this file (before `backend.main` was ever
    imported, which is the only time that matters). This fixture is just the skip gate for
    the tests that need it: `pytest.skip(...)` here, not an assert, because "no npm on this
    machine" is a missing tool, not a defect in the app.
    """
    if FRONTEND_UNAVAILABLE_REASON:
        pytest.skip(FRONTEND_UNAVAILABLE_REASON)
    return _FRONTEND_DIST


@pytest.fixture
def repo_root() -> Path:
    return _REPO_ROOT


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

