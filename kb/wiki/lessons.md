---
name: lessons
description: Durable lessons this project has learned
type: reference
---

# lessons

Durable lessons land here as the project runs — one entry per lesson, newest first, each
citing the ticket/incident it came from.

## "Nothing was added" is not proof that a rollback happened (T-15)

T-15 had to prove T-10's atomicity guarantee still holds with a concurrent fetch phase in
front of the insert loop: force a failure mid-commit inside a 500-row batch, show the row
count unchanged. The obvious test does exactly that and can pass for entirely the wrong
reason. `import_commit` resolves every record BEFORE it opens a transaction, and a failure
in that phase is recorded in `failures` and skipped — so if the sabotage lands in the fetch
rather than in an `INSERT`, the endpoint returns a perfectly correct answer, nothing is
added, the row count is unchanged, and **the transaction was never exercised at all**. The
test is green and the rollback is untested.

So the assertion has to be about what the transaction DID before it died, not only about
what survived. `tests/test_import_atomicity.py` counts the INSERTs that actually executed
and requires 251 of them — rows 0–249 succeeded, row 250 raised — because that number is the
only thing separating "one transaction that rolled back" from "the failure happened before
any writing started". Watch it fail, too: with the single `with connection()` replaced by a
connection per row, the same test reports `assert 252 == 2`, i.e. 250 rows survived.

The general form: **when a test proves an absence, prove the presence of the thing that was
supposed to make the absence hard.** An absence has too many causes.

## `TestClient` collects the whole response body before you can read a line of it (T-15)

AC3 needed proof that `/api/import/preview` reports progress *while it is still resolving*.
The obvious test streams the endpoint and timestamps each event:

```python
with client.stream("POST", "/api/import/preview", json={"text": csv}) as response:
    for line in response.iter_lines():   # every line arrives at the same instant
```

Every timestamp came back within 1ms of every other, on a request that genuinely takes ~1.4
seconds over a real socket. The server was streaming perfectly; the client is not.
`starlette.testclient._TestClientTransport.handle_request` writes each `http.response.body`
message into an `io.BytesIO` and finishes with
`raw_kwargs["stream"] = httpx.ByteStream(raw_kwargs["stream"].read())` — the response is
fully materialised before httpx ever hands it back. `iter_lines()` is then iterating a
buffer, and any timing assertion built on it is measuring that buffer.

This is the same trap as the path-traversal lesson below, in a different costume: **the
in-process test client is the one thing that cannot reproduce the property under test.** The
fix is the same shape, too — test the layer that does the work. `_preview_events` is an async
generator, so driving it directly and timestamping each `yield` measures exactly what a
socket reader would see, with nothing in between. Confirmed separately against a real uvicorn
on loopback: `transfer-encoding: chunked`, 246 progress events, first at 561ms, 50% at 971ms,
result at 1357ms.

Corollary for the other direction: **a latency stub that returns instantly cannot measure
concurrency.** A sequential loop and an eight-way-concurrent one over zero-cost awaits
produce the same wall clock, so the "after" number would have looked like a win with nothing
changed. `tests/test_import_scale.py`'s stubs sleep 2ms for exactly this reason, and the
sabotage run (`SEARCH_CONCURRENCY = 1`) is what proves the ceiling can still fail.

## A concurrency cap is not a rate limit, and 429 here is silent (T-15)

Two separate ceilings, and bounding one does nothing for the other. Eight requests in flight
at 200ms each is **40 requests/second** — ten times IGDB's published limit of 4/s, even
though "8 at once" is precisely IGDB's own open-request cap. `backend/sources/base.py`
carries both numbers per source for that reason: `open_requests` is a semaphore,
`per_second` is a departure clock, and a request has to satisfy both.

What makes this correctness rather than manners in this codebase: `raise_for` turns HTTP 429
into a `SourceError`, and the import resolver catches `SourceError` **per row** and marks
that row `unmatched`. Crossing the limit therefore does not fail loudly — it quietly turns a
thousand-row import into a thousand rows that "have no match", on the owner's real list, with
nothing anywhere saying the upstream refused. Before adding concurrency to anything that
talks to a rate-limited service, find out what that service does on refusal and what the
caller does with the refusal; if the answer is "swallows it per item", the bound is load
bearing.

## `asyncio.Lock`/`Semaphore` bind to the first event loop that touches them (T-15)

A module-scope `asyncio.Lock()` works in the first test and raises
`... is bound to a different event loop` in the second, because each `TestClient` (and each
`asyncio.run`) is a fresh loop while the singleton is not. The primitive latches its loop on
first use and never lets go. So any long-lived limiter, pool or gate that lives at module
scope has to rebuild its primitives when the running loop changes — `RateLimit._bind()` does
exactly that, and resetting the pacing clock alongside them is correct rather than sloppy,
since a new loop means none of our requests are in flight.

Two smaller ones from the same ticket, worth knowing before losing an hour to either:
`asyncio.gather` does **not** cancel its siblings when one child raises (only when the gather
itself is cancelled), so an unexpected failure leaves the other hundreds of tasks running
against the upstreams for a response nobody will read — cancel them explicitly. And
`sqlite3.Connection` has no instance `__dict__`, so `conn.execute = wrapper` is an
`AttributeError`, not a seam; `conn.set_trace_callback(fn)` is sqlite3's own hook and fires
per statement, the failing one included.

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
