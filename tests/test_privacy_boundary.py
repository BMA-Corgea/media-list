"""AC3 — the privacy boundary is a test, not a habit.

Two independent guarantees, both real defects in this project's own history:

1. `git check-ignore` on `data/`, a `*.db` file and `.env` — the owner's list must never be
   one `git add -A` away from the public repo.
2. The SPA catch-all's containment check (`backend/main.py::spa`) — T-2's fallback once
   served the real `.env`, API keys and all, to a client that sent the path raw
   (`curl --path-as-is`; browsers normalise `..` away before the server ever sees it, other
   clients do not).

Needs `frontend/dist` to exist: the catch-all route in `create_app()` is only registered
`if dist.is_dir()`, decided once at import — see the top of conftest.py for why that build
has to happen before `backend.main` is ever imported, not lazily in this file.
"""

from __future__ import annotations

import subprocess

import pytest


def _is_ignored(repo_root, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=repo_root, capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize("relative_path", [
    "data/",
    "data/media-list.db",
    "data/art/whatever.jpg",
    ".env",
    "media-list-export.csv",
    "media-list-export-2026-01-01.csv",
    "some-random-file.db",
])
def test_privacy_paths_are_gitignored(repo_root, relative_path):
    assert _is_ignored(repo_root, relative_path), (
        f"{relative_path!r} is NOT gitignored — it would be one `git add -A` away from "
        "the public repo."
    )


def test_env_example_is_deliberately_not_ignored(repo_root):
    """The template must stay trackable, or a fresh clone has nothing to copy from."""
    assert not _is_ignored(repo_root, ".env.example")


@pytest.mark.parametrize("traversal_path", [
    "/../.env",
    "/../../.env",
    "/../../../.env",
    "/%2e%2e/%2e%2e/.env",
    "/assets/../../../.env",
    "/../.git/config",
    "/../../../../../../etc/passwd",
])
def test_spa_traversal_never_escapes_dist(client, frontend_dist, traversal_path):
    """`--path-as-is`-style raw traversal payloads (T-2's own regression) must always fall
    through to the SPA shell, never to a real file outside `frontend/dist`."""
    resp = client.get(traversal_path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in resp.text.lower() or "<html" in resp.text.lower()


def test_spa_traversal_does_not_leak_a_real_secret_file(client, frontend_dist, repo_root):
    """Plants a throwaway `.env` (this worktree ships none) with a canary value, proves a
    traversal request for it comes back as the SPA shell and never as the file's content —
    this is the literal shape of T-2's original defect."""
    marker = "MEDIA_LIST_TEST_CANARY_SECRET_VALUE"
    env_path = repo_root / ".env"
    assert not env_path.exists(), "refusing to overwrite an existing .env"
    env_path.write_text(f"TMDB_API_KEY={marker}\n")
    try:
        for path in ("/../.env", "/../../.env", "/assets/../../.env"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert marker not in resp.text
            assert "TMDB_API_KEY" not in resp.text
    finally:
        env_path.unlink()


def test_api_routes_are_never_swallowed_by_the_spa_catchall(client, frontend_dist):
    """Guard the guard: `/api/...` and `/art/...` must still resolve as JSON 404s, not HTML —
    a catch-all that ate those would fail silently (`backend/main.py::spa`'s own docstring)."""
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")

    resp = client.get("/art/does-not-exist.jpg")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_a_normal_spa_route_still_serves_the_shell(client, frontend_dist):
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
