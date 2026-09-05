---
name: lessons
description: Durable lessons this project has learned
type: reference
---

# lessons

Durable lessons land here as the project runs — one entry per lesson, newest first, each
citing the ticket/incident it came from.

## A cached WebKit binary is not a working WebKit — two of its runtime libraries aren't in this machine's own Ubuntu repos (T-14)

`~/.cache/ms-playwright/webkit-2336` (the build pinned by `@playwright/test@1.62.1`, chosen
specifically to reuse this cache — see AC1) is fully downloaded, and `MiniBrowser` is a real
executable. It still cannot launch:

```
Error: browserType.launch:
Host system is missing dependencies to run browsers.
Please install them with: sudo npx playwright install-deps
```

`ldd` against the actual GTK library (with `LD_LIBRARY_PATH` set the way Playwright sets it)
names four missing `.so`s: `libavif.so.16`, `libgstcodecparsers-1.0.so.0`, `libjxl.so.0.8`,
`libbacktrace.so.0`. This machine is Ubuntu **24.04.2 LTS (noble)** — checked via
`/etc/os-release`, and worth stating plainly because this is the same machine the owner
develops on, not a disposable CI box. Downloading the two packages Playwright's own
`install-deps` list actually names (`libavif16`, `libgstreamer-plugins-bad1.0-0` — fetchable
with plain `apt-get download`, no root needed, then `dpkg-deb -x` to inspect) resolves
`libavif.so.16` and `libgstcodecparsers-1.0.so.0` cleanly. The other two do not have a fix
this simple:

- **`libjxl.so.0.8` does not exist in noble's archives at any component or pocket.**
  `apt-cache madison libjxl0.7` — the only libjxl shared-lib package Ubuntu ships — tops out
  at `0.7.0`. This WebKit build was linked against a newer JPEG-XL ABI than Ubuntu 24.04
  packages at all, full stop, not "not installed yet."
- **`libbacktrace.so.0` has no providing package in the Ubuntu index either** (no `apt-file`
  hit, no `libbacktrace0`/`libbacktrace1` candidate — Debian/Ubuntu do not ship GCC's
  `libbacktrace` as a public shared object the way some other distros do).

The consequence: **`sudo npx playwright install-deps` would not actually fix this host.**
That command's own package list only covers the two libraries this ticket also resolved by
hand; it does not mention `libjxl` or `libbacktrace` at all, so running it as root would still
leave WebKit unable to launch. The honest fix is Microsoft's own `mcr.microsoft.com/playwright`
Docker image (built on whatever base actually satisfies this WebKit revision) or a newer
host distro — not a package this repo, or a `sudo` invocation on this machine, can supply.

**Cost of the workaround not taken:** none was applied. `playwright.config.js` still declares
a `webkit` project (AC5's "wired in" is about the runner, not about this host being able to
run it), and `scripts/test.sh --browsers` attempts it honestly — it fails loudly with the
exact Playwright error above rather than being silently skipped. T-14 shipped real, repeatable,
green coverage on **Chromium and Firefox only** in this environment; WebKit's specs are
written and will run the moment they execute somewhere with matching system libraries, but
nobody should read "webkit project exists in the config" as "WebKit passed here." It did not
run at all. (And when it does run somewhere: it's still a Linux WebKit build, not Safari.)

## Playwright's own inter-event timing, not a browser engine, is what starves a "velocity from the last pointermove" throw (T-14)

The carousel's throw physics (`frontend/src/carousel.js`) compute velocity from ONLY the
delta since the immediately-previous `pointermove` — `-((event.clientX - lastX) / CARD_STEP)
* (16 / dt)` — overwritten on every move, never accumulated. That is a reasonable design for
real input (consecutive samples from one continuous gesture are normally close together in
time), but it means the THROW's momentum is entirely at the mercy of whichever `pointermove`
happens to land last before `pointerup`.

A first attempt at a "flick" test used `page.mouse.move(x, y, { steps: 2 })` — deliberately
imitating a fast, coarse drag. Direct measurement (listening for real `pointermove` timestamps
via `performance.now()`) showed the gap between the last two synthesized move events swinging
from ~5ms to over 150ms, **on both Chromium and Firefox**, run to run, for the identical
gesture. When that final gap happened to be large, the resulting velocity fell under
`MIN_VELOCITY` (0.02) and the settle loop skipped the momentum branch entirely, snapping
straight back to the start card — reproduced empirically at roughly a 30-70% failure rate on
Firefox across repeated real `npx playwright test` runs (7 failures in 10; then 15/15 clean
after the fix below), fewer observed on Chromium in the same sampling but the same underlying
jitter was present in its raw timestamps too.

The fix is a TEST change, not an app change: `steps: 1` (one decisive jump, not several
interpolated ones) gives the gesture exactly one `pointermove`, whose delay since
`pointerdown` measured consistently around 14-16ms on both engines across 8 trials each —
compare the 5-150ms spread `steps: 2` produced. `tests/browser/wall.spec.js`'s momentum test
uses `steps: 1` for exactly this reason. The underlying app code was never touched: this is a
Playwright-multi-step-drag characteristic, not a defect in either engine's Pointer Events
implementation, and rewriting the carousel's velocity math to smooth over uneven real-world
input was out of this ticket's scope (AC4 — a fix belongs in the layer it belongs to, and nothing
here showed the *shipped* feel was actually broken for a real mouse or trackpad).

## An optimistic UI reorder can look "done" on screen before the request that would actually confirm it has even landed (T-14)

`views/queue.js`'s drag-reorder repaints the list live during the drag itself (`insertBefore`
on every threshold crossing, inside `pointermove`) — the row visually settles into its new
slot well before `endDrag` ever calls `commit()` → `api.move()`. A browser-test assertion that
checks `.qrow` DOM order right after the gesture (even via `expect.poll`) can therefore pass
on its very first attempt for a reason that has nothing to do with the server: the reorder it
is "confirming" is the same optimistic DOM state the drag itself already produced, not
evidence the `POST /titles/{id}/move` request has completed.

This surfaced as a real, reproducible (not one-off) Firefox failure: a trace (`trace: 
'retain-on-failure'`, extracted with plain `unzip`) showed the move request's own network
entry recorded with `"status": -1` — the harness's test-teardown closed the page before a
response the request was still waiting on ever arrived, and the row's server-side position
was left completely unchanged (byte-identical to its seeded value) despite the DOM already
showing the "corrected" order. The fix: arm `page.waitForResponse(...)` for the `/move`
request **before** starting the drag (`Promise.all`, not two sequential `await`s — a response
that lands in the gap between arming and starting would otherwise be missed), and don't check
anything else until that response is confirmed `.ok()`. `tests/browser/queue.spec.js`'s
`dragAndWaitForMove` helper is this pattern. The lesson generalises past this one ticket:
**for any optimistic-UI surface, wait for the network call that makes a change real, not
the visual state a client update already produced for free** — the same shape as T-13's
"a test you have never watched fail is not a regression test," one layer up the stack.

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
