"""AC3 — the privacy boundary is a test, not a habit.

Two independent guarantees, both real defects in this project's own history:

1. `git check-ignore` on `data/`, a `*.db` file and `.env` — the owner's list must never be
   one `git add -A` away from the public repo.
2. The SPA catch-all's containment check (`backend/main.py::spa`) — T-2's fallback once
   served the real `.env`, API keys and all, to a client that sent the path raw.

READ THIS BEFORE ADDING A TRAVERSAL CASE (T-13 round 2, the defect this file used to have)
------------------------------------------------------------------------------------------
`TestClient` is built on **httpx**, and httpx normalises the URL it is handed *before the
request ever enters the app*: RFC 3986 dot-segment removal turns `GET /../../.env` into
`GET /.env` client-side. So a traversal test written the obvious way — `client.get("/../../.env")`
— never delivers a `..` to the handler at all. It passes because `dist/.env` does not exist,
not because anything was blocked, and it would go on passing with the containment check
deleted.

A *real* client does not do that. Measured against a live uvicorn on loopback with
`curl --path-as-is` (T-13 evidence): `/../../.env` arrives at the handler as `../../.env`,
traversal fully intact. Uvicorn and Starlette do **not** collapse dot segments; only the
test client does.

So containment is covered here in three layers, in descending order of how much work they do:

* **Direct calls** (`spa_endpoint`) with raw `../../.env` strings — the shape a real
  non-normalising client delivers, exercised with no HTTP layer in between to soften it.
  This is the load-bearing layer.
* **Percent-encoded payloads** over HTTP (`%2e%2e`, `%2E%2E`, `..%2f`, doubly-encoded) —
  these survive httpx's normaliser and do reach the handler with traversal intact.
  `test_percent_encoded_dots_really_reach_the_handler` is the tripwire on that claim: if a
  future httpx/Starlette starts decoding-then-collapsing these too, it fails loudly instead
  of letting this layer go quietly blind.
* **Plain payloads** over HTTP — kept as a cheap third layer, honestly labelled: they are
  collapsed before they arrive and prove only that the collapsed form is also harmless.

The canary file is planted under pytest's `tmp_path`, never at the repo root: the repo root
is not a sandbox — on the owner's machine it holds a live `.env` and `data/`, and a test that
writes, unlinks, or asserts the absence of anything there fails on the one machine this suite
exists to protect.

Needs `frontend/dist` to exist: the catch-all route in `create_app()` is only registered
`if dist.is_dir()`, decided once at import — see the top of conftest.py for why that build
has to happen before `backend.main` is ever imported, not lazily in this file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from starlette.responses import FileResponse

from backend.main import app

#: Planted in a throwaway file the test owns, then hunted for in every response body.
CANARY = "MEDIA_LIST_TEST_CANARY_SECRET_VALUE"


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


# ── the SPA containment check (T-2's defect) ─────────────────────────────────────────────


@pytest.fixture
def spa_endpoint(frontend_dist):
    """`backend.main.spa` itself, looked up from the live route table at call time.

    Calling the endpoint directly is the only way to test containment against the payload a
    non-normalising client really sends (`curl --path-as-is`): every HTTP client in this
    process collapses `..` before the request leaves it. Looked up rather than imported
    because `spa` is a closure defined inside `create_app()` — and looked up *per test*, so a
    harness that swaps the route in (T-13's proof that these tests can fail) is honoured.
    """
    for route in reversed(app.router.routes):
        if getattr(route, "path", None) == "/{full_path:path}":
            return route.endpoint
    pytest.fail(
        "no /{full_path:path} catch-all is registered on the app — either frontend/dist was "
        "missing when backend.main was imported (see conftest.py) or the SPA route is gone."
    )


def _served_file(response) -> Path:
    """The file a handler actually decided to serve, resolved."""
    assert isinstance(response, FileResponse), (
        f"expected a FileResponse from the SPA catch-all, got {type(response).__name__}"
    )
    return Path(response.path).resolve()


def _plant_canary(tmp_path: Path) -> Path:
    """A real, readable, secret-bearing file OUTSIDE frontend/dist — never at the repo root.

    Bait with substance: containment only proves something against a target that genuinely
    exists, because `FileResponse` on a missing path would fall through to the shell anyway
    and a test built on a non-existent file passes for the wrong reason.
    """
    secret = tmp_path / "planted-secrets" / ".env"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text(f"TMDB_API_KEY={CANARY}\nIGDB_CLIENT_SECRET={CANARY}\n")
    return secret


def _raw_traversal_to(target: Path, dist: Path) -> str:
    """The literal `../../..`-style path a client would send to reach `target` from the SPA
    root — computed, not hard-coded, so it works from whatever directory the checkout sits in.
    """
    return os.path.relpath(target.resolve(), dist.resolve())


def _percent_encode_dots(raw: str) -> str:
    """`../../x` -> `%2e%2e/%2e%2e/x`: the same traversal, spelled so httpx forwards it."""
    return "/".join("%2e%2e" if segment == ".." else quote(segment) for segment in raw.split("/"))


#: Raw handler-level payloads — what a real `curl --path-as-is` client puts on the wire.
#: Shape coverage only: how far up each of these actually climbs depends on how deep the
#: checkout sits, so none of them is guaranteed to land on a file that exists. The tests that
#: aim at a target known to exist compute the depth with `os.path.relpath` instead — never
#: hard-code a `../` count, or the payload lands somewhere harmless on a deep checkout and
#: the test passes for a reason that has nothing to do with containment (T-13's own finding).
RAW_TRAVERSAL_PAYLOADS = [
    "../.env",
    "../../.env",
    "../../../.env",
    "assets/../../../.env",
    "../.git/config",
    "../../data/media-list.db",
]


@pytest.mark.parametrize("raw_path", RAW_TRAVERSAL_PAYLOADS)
def test_spa_containment_holds_when_the_route_is_called_directly(spa_endpoint, frontend_dist, raw_path):
    """Containment against the shapes a real non-normalising client sends: no HTTP layer,
    no client-side normaliser, just the check itself.

    These are shape coverage — the two tests below (a file that really exists, and a planted
    secret) are what make the layer able to fail."""
    served = _served_file(spa_endpoint(raw_path))
    assert served == (frontend_dist / "index.html").resolve(), (
        f"spa({raw_path!r}) escaped frontend/dist and served {served} — this is T-2, "
        "the defect that once handed out the owner's real API keys."
    )


def test_spa_containment_never_serves_a_planted_secret_when_called_directly(
    spa_endpoint, frontend_dist, tmp_path,
):
    """T-2's literal shape: a real secret file, a real traversal that reaches it, and the
    proof that what comes back is the shell and not the secret."""
    secret = _plant_canary(tmp_path)
    raw = _raw_traversal_to(secret, frontend_dist)

    # Sanity on the test's own setup, so it can never pass by being toothless.
    assert raw.startswith("../"), f"{raw!r} is not a traversal — the canary is not outside dist"
    assert CANARY in secret.read_text(), "the bait file lost its canary"
    assert (frontend_dist / raw).resolve() == secret.resolve(), (
        f"{raw!r} does not actually resolve to the planted secret — the payload is wrong"
    )

    served = _served_file(spa_endpoint(raw))
    assert served == (frontend_dist / "index.html").resolve()
    assert CANARY not in served.read_text(errors="replace")


#: Percent-encoded payloads: these survive httpx's dot-segment removal and arrive at the
#: handler as real `..` (measured — see this module's docstring and T-13's evidence).
ENCODED_TRAVERSAL_PAYLOADS = [
    "/%2e%2e/%2e%2e/.env",
    "/%2E%2E/%2E%2E/.env",                                    # case-insensitive escapes
    "/%2e%2e%2f%2e%2e%2f.env",                                # encoded separators too
    "/..%2f..%2f.env",                                        # mixed: plain dots, encoded slash
    "/%252e%252e/%252e%252e/.env",                            # doubly encoded
    "/assets/../%2e%2e/.env",                                 # half-normalised by the client
    "/%2e%2e/.git/config",
    "/%2e%2e/%2e%2e/data/media-list.db",                      # the owner's list, by name
]


def _shell(frontend_dist: Path) -> str:
    return (frontend_dist / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("traversal_path", ENCODED_TRAVERSAL_PAYLOADS)
def test_encoded_traversal_over_http_returns_the_shell(client, frontend_dist, traversal_path):
    """Layer two: traversal that survives the client's normaliser, over the real ASGI stack."""
    resp = client.get(traversal_path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html"), (
        f"{traversal_path} came back as {resp.headers['content-type']} — the catch-all "
        "served something that is not the SPA shell"
    )
    assert resp.text == _shell(frontend_dist)


def test_percent_encoded_dots_really_reach_the_handler(client, frontend_dist):
    """The tripwire on layer two — proves these payloads still carry traversal.

    Walks out of `dist` and back in to a real built asset. If the handler receives `..`
    intact the path resolves back inside `dist` onto a genuine file and is served with that
    file's own content type; if some future httpx/Starlette decodes `%2e%2e` and then
    collapses it, `full_path` becomes `dist/assets/<file>`, nothing exists there, and the
    shell (`text/html`) comes back instead. So a content type of `text/html` here means the
    entire encoded layer above has quietly stopped testing containment — exactly the way
    this file was broken before (T-13 round 1).
    """
    assets = sorted((frontend_dist / "assets").glob("*.css")) or \
        sorted((frontend_dist / "assets").glob("*.js"))
    assert assets, "no built asset to aim at"
    out_and_back = f"/%2e%2e/{frontend_dist.name}/assets/{assets[0].name}"

    resp = client.get(out_and_back)
    assert resp.status_code == 200
    assert not resp.headers["content-type"].startswith("text/html"), (
        f"{out_and_back} returned the SPA shell, which means the `%2e%2e` never reached "
        "backend.main::spa as `..`. The encoded payloads in ENCODED_TRAVERSAL_PAYLOADS are "
        "no longer exercising the containment check — fix them before trusting this file."
    )
    assert resp.content == assets[0].read_bytes()


def test_encoded_traversal_does_not_leak_a_planted_secret(client, frontend_dist, tmp_path):
    """The canary, over HTTP this time: a real secret file outside dist, addressed by a
    computed traversal, requested through the whole stack."""
    secret = _plant_canary(tmp_path)
    raw = _raw_traversal_to(secret, frontend_dist)
    encoded = "/" + _percent_encode_dots(raw)
    assert "%2e%2e" in encoded, f"{encoded!r} carries no encoded traversal"

    resp = client.get(encoded)
    assert resp.status_code == 200
    assert CANARY not in resp.text, "the SPA catch-all served a real secret file (T-2)"
    assert "TMDB_API_KEY" not in resp.text
    assert resp.text == _shell(frontend_dist)


#: Plain payloads. httpx removes the dot segments client-side before the app ever sees them
#: (`/../../.env` is sent as `/.env`), so these do NOT exercise containment — they are the
#: cheap third layer, kept because the collapsed spelling is worth pinning too.
NORMALISED_TRAVERSAL_PAYLOADS = [
    "/../.env",
    "/../../.env",
    "/../../../.env",
    "/assets/../../../.env",
    "/../.git/config",
]


@pytest.mark.parametrize("traversal_path", NORMALISED_TRAVERSAL_PAYLOADS)
def test_client_normalised_traversal_also_returns_the_shell(client, frontend_dist, traversal_path):
    """Layer three, honestly labelled: httpx collapses these before they leave the client, so
    they land as `/.env`, `/etc/passwd` and so on. They prove the collapsed form is harmless
    too — they do not prove containment works. The direct-call tests do that."""
    resp = client.get(traversal_path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == _shell(frontend_dist)


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


def test_the_assets_mount_cannot_be_traversed_either(client, frontend_dist, tmp_path):
    """`/assets` is a separate attack surface: a `StaticFiles` mount, not the catch-all.

    It is matched before `spa()` ever runs, so it carries its own containment (Starlette's)
    and answers a traversal with 404 rather than the shell. Either answer is fine; serving
    the planted secret is not. Kept as its own test because asserting "the SPA shell" here
    would be asserting the wrong thing about the wrong route.
    """
    secret = _plant_canary(tmp_path)
    raw = _raw_traversal_to(secret, frontend_dist / "assets")
    resp = client.get("/assets/" + _percent_encode_dots(raw))

    assert resp.status_code in (200, 404), resp.status_code
    assert CANARY not in resp.text, "the /assets mount served a real secret file"
    assert "TMDB_API_KEY" not in resp.text


#: Files that exist outside `frontend/dist` on any Linux box, used as bait the test did not
#: create itself. The traversal that reaches them is *computed* per checkout, never guessed.
REAL_FILES_OUTSIDE_DIST = [
    path for path in (Path("/etc/passwd"), Path("/etc/hostname")) if path.is_file()
] or [pytest.param(None, marks=pytest.mark.skip(reason="no well-known file outside dist here"))]


@pytest.mark.parametrize("target", REAL_FILES_OUTSIDE_DIST, ids=str)
def test_spa_containment_holds_against_a_real_file_outside_dist(spa_endpoint, frontend_dist, target):
    """The direct-call layer, aimed at something that genuinely exists and is genuinely
    outside dist. Without the containment check in `spa()` this hands the file straight back."""
    raw = _raw_traversal_to(target, frontend_dist)
    assert (frontend_dist / raw).resolve() == target.resolve(), (
        f"{raw!r} does not reach {target} — the payload, not the app, is wrong"
    )
    served = _served_file(spa_endpoint(raw))
    assert served == (frontend_dist / "index.html").resolve(), (
        f"spa({raw!r}) served {served} instead of the shell — containment is gone (T-2)."
    )


@pytest.mark.parametrize("target", REAL_FILES_OUTSIDE_DIST, ids=str)
def test_encoded_traversal_to_a_real_file_outside_dist_returns_the_shell(client, frontend_dist, target):
    """The same bait over HTTP, spelled so httpx forwards the traversal instead of eating it."""
    encoded = "/" + _percent_encode_dots(_raw_traversal_to(target, frontend_dist))
    resp = client.get(encoded)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == _shell(frontend_dist)
