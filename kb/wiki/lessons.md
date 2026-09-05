---
name: lessons
description: Durable lessons this project has learned
type: reference
---

# lessons

Durable lessons land here as the project runs — one entry per lesson, newest first, each
citing the ticket/incident it came from.

## A path-traversal test written the obvious way tests nothing — the HTTP client eats the `..` (T-13)

`client.get("/../../.env")` never delivers a `..` to the handler. `TestClient` is built on
**httpx**, and httpx applies RFC 3986 dot-segment removal to the URL *before the request
leaves the client*: what goes on the wire is `GET /.env`. The handler sees `full_path=".env"`,
`dist/.env` does not exist, the SPA shell comes back, the test goes green — and it would go on
green with the containment check in `backend/main.py::spa` deleted. T-13's first attempt
shipped exactly that: all 18 tests in `tests/test_privacy_boundary.py`, including the one
named *does not leak a real secret file*, passed against a copy of `spa()` with containment
removed (T-2's pre-fix shape).

The collapse is the **client's**, not the server's. Measured against a live uvicorn on
loopback with `curl --path-as-is`:

| sent raw | reaches the handler as | via TestClient |
| --- | --- | --- |
| `/../../.env` | `../../.env` — **intact** | `.env` (collapsed by httpx) |
| `/%2e%2e/%2e%2e/.env` | `../../.env` | `../../.env` |
| `/..%2f..%2f.env` | `../../.env` | `../../.env` |
| `/%252e%252e/%252e%252e/.env` | `%2e%2e/%2e%2e/.env` (decoded once) | `../../.env` (decoded twice) |

So the exploit is entirely real against a real server — uvicorn and Starlette do not remove
dot segments — and the in-process test client is the one thing that cannot reproduce it in its
plainest form. Note the last row: TestClient decodes once into `scope["path"]` and Starlette's
path convertor unquotes again, so a doubly-encoded payload behaves *differently* under
`TestClient` than under uvicorn. Neither is dangerous here (containment catches both), but do
not reason about encoding from the test client alone.

What to do when writing one of these:

1. **Call the route function directly** with the raw string a non-normalising client sends.
   No HTTP layer, nothing to soften the payload. This is the layer that does the work.
2. **Percent-encode** (`%2e%2e`, `%2E%2E`, `..%2f`) for the over-HTTP layer, and add a
   tripwire proving those still arrive as `..` — walk out of the served root and back in to a
   real asset and check the content type. If some future httpx collapses those too, the
   tripwire fails loudly instead of the whole layer going quietly blind.
3. **Aim at a file that exists.** Traversal to a missing path falls through to the shell
   anyway, so the test passes without proving anything. Plant a canary (under `tmp_path`,
   never at the repo root — see the next lesson) or use `/etc/passwd`.
4. **Never hard-code a `../` depth.** `../../../../../../etc/passwd` climbs out of an
   eight-deep worktree into `/tmp/claude-1000/etc/passwd`, which does not exist — the case
   then passes on a miss. Compute it: `os.path.relpath(target, served_root)`.

The rule underneath all four: **a regression test you have never watched fail is not a
regression test.** Strip the check out of a *copy* of the code and run the test against it.
Five minutes, and it is the only thing that distinguishes a guard from a decoration.

## The repo root is not a sandbox — plant test fixtures under `tmp_path` (T-13)

The same file asserted `not (repo_root / ".env").exists()` before writing a canary there. In
a disposable worktree that is true and the suite is green; on the owner's machine `.env` is a
live file with real API keys, so the suite failed on the one checkout it exists to protect —
and the failure was in the privacy test, which reads like a breach until you look. A test
must never write to, unlink, or depend on the *absence* of anything at the repo root: that
tree carries `.env`, `data/` and the owner's database. `tmp_path` is free and is deleted for
you; if a test needs a file at a particular *position* relative to the app (outside the
served root, say), compute the path to it rather than moving the file to where the arithmetic
is easy.

## `from module import name` binds a NAME, not a live reference back to the source module (T-13)

`backend/sources/tmdb.py`, `igdb.py`, `anilist.py` and `backend/artwork.py` all do
`from .sources.base import client` (or `from .base import client`). Each of those is its own
binding in the importing module's `__dict__`, made once at import time. **Monkeypatching
`backend.sources.base.client` does nothing to any of the other four** — they still hold the
original function object.

The rule this generalises to: before patching a shared helper for a test (or swapping an
implementation at runtime for any reason), grep every place it is imported and check *how*.
`import module` then `module.thing` stays live because the attribute lookup happens at call
time on the shared module object. `from module import thing` freezes a reference at import
time and needs patching wherever it landed. `tests/conftest.py::no_network` patches all five
module-level `client` bindings for exactly this reason — see its docstring for the full list.

## Module-scope side effects mean setup has to happen before FIRST import, not after (T-13)

`backend/config.py` builds `config = load_config()` at import. `backend/main.py` ends with
`app = create_app()` at module scope, which calls `bootstrap()` (creates/opens the database)
**and** decides once, via `dist.is_dir()`, whether the SPA catch-all route exists at all. A
fixture, test, or script that wants a different `MEDIA_LIST_DB`, or wants the SPA route to
exist, has to arrange that reality before `backend.main` — or even `backend.config` — is
imported for the first time in the process. After that point the decision is already baked
into the frozen `config` singleton or the registered route table, and nothing short of
re-importing (which Python won't naturally do) changes it.
`tests/conftest.py` is structured with a hard comment marker for exactly this reason: an
environment-setting line below the "everything past here may import backend" marker is a
bug, not a style choice.

## Evidence and plan documents describe intent; the code is the actual contract (T-13)

`.autodev/plans/T-13.md` described star validation as "0–5 integers accepted". The code
(`backend/main.py::update_title`) enforces `1 <= stars <= 5` — 0 is rejected — and T-9's own
evidence table already recorded `0 -> 400`. The plan was simply imprecise. When freezing
behaviour into tests, read the code path being frozen directly rather than trusting a prose
description of it, even one written for this exact ticket; use evidence documents to learn
*what to test*, not to learn *what the correct answer is*.

## `python-dotenv`'s `load_dotenv` does not override an already-set environment variable (T-13)

`config.py`'s own docstring says as much ("real environment variables win over it"), and it
is the lever that makes test credentials deterministic: setting `TMDB_API_KEY` (etc.) in
`os.environ` *before* `backend.config` is imported means the module's own
`load_dotenv(REPO_ROOT / ".env")` call is a no-op for those names, regardless of whether a
real `.env` with real keys happens to sit next to the code being tested.
