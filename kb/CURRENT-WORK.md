# CURRENT WORK — media-list

## 2026-09-07 — the board is CLEAR. 18 of 18 tickets complete.

`main` @ `193b65a`, **pushed** — `origin/main` is level. Everything below is on the public repo
at github.com/BMA-Corgea/media-list.

| | |
| --- | --- |
| Run it | `./start.sh` → `http://127.0.0.1:7799` |
| Test it | `scripts/test.sh` · `scripts/test.sh --browsers` |
| Suites | **203 pytest** passed, 1 skipped · **66 browser** passed on chromium + firefox |
| The list | **EMPTY, and that is correct** — the owner wiped the fixture rows 2026-09-07 |
| Kinds | anime · movie · live-action · game · **book** |
| Sources | TMDB + AniList (screen) · IGDB (games) · **Open Library (books)** · Pexels (chrome only) |

### What shipped today

**T-18 — back from a candidate keeps the search.** Two review rounds. Round 1 caught a router
race that would have silently reintroduced the bug; round 2's fix for it introduced a
cleanup leak, found by instrumenting the real bundle, fixed in the same round rather than
deferred. **App-wide behaviour change: a view is dismissed when the user LEAVES it, not when
its replacement is ready** — T-15's import stream now cancels at the click. A full page reload
deliberately does NOT restore the search; that is a recorded choice.

**T-16 — books as a fifth kind.** The migration was the risk and it was earned: round 1
re-derived the interrupt-safety claim with an external `SIGKILL` (30 kills, 0 failures) rather
than trusting the builder's in-process `os._exit`. Verified LIVE on the owner's own database:
`user_version` 1 → 2, `isbn` added, both CHECK constraints rewritten, no staging debris. A book
was searched, fetched, added and then **deleted again** — proving the feature must not cost him
the clean slate he asked for.

### Two lessons worth more than the tickets

1. **In a hash router, `toHaveURL` is not evidence a screen was ever mounted.** The hash updates
   the address bar before the router resolves anything. That was the tenth green-but-empty test
   here. Assert on something only the destination renders. (`kb/wiki/lessons.md`)
2. **An error path must not destroy its own diagnosis.** Twice in one day: T-16's F6, where a
   bare `ROLLBACK` replaced the disk-full error that caused it; and `/api/search`, where
   `str(httpx.ConnectTimeout())` is the EMPTY STRING, so a dead source was named with no reason
   at all. Both fixed. **Found by driving the app, not by running the suite.**

### Known and accepted, not open

- **Open Library connect-times-out intermittently** (~1 in 6 by hand). Upstream, not ours. The
  app degrades correctly — other sources still answer and the dead one is named — and now says
  `ConnectTimeout` instead of nothing. Deliberately NOT fixed by raising the timeout, which
  would only hide upstream slowness.
- **WebKit cannot launch on this host** — needs `libjxl.so.0.8` + `libbacktrace.so.0`; Ubuntu
  24.04 ships `libjxl0.7`. Two engines by the owner's decision: *"Go with (a), two engines is
  fine."* The command fails loudly rather than skipping.
- **No lint or typecheck exists in this repo** — no ESLint, Prettier, tsconfig, ruff, flake8,
  pre-commit. Stage contracts name them; they do not exist. Never read "lint green" into a pass.
- **CSV import asks IGDB about every row** (~251s per 1000 rows). His decision, to keep the
  mis-declared-row rescue. Do not "optimise" it without asking.
- **The momentum test is load-sensitive** (`tests/browser/wall.spec.js:98`). His decision: leave
  it, it tells the truth.
- **Name + email remain in published history.** His decision: leave them. Do not raise again.

### The next real thing

The owner's own list. He planned to generate it by chatting with ChatGPT using the prompt in
`README.md`, then `#/transfer` → Preview → settle ambiguous rows → Import. Expect ~4 minutes for
a large file, by his own choice.

---

## 2026-09-07 — T-18 MERGED, at Evan's accept gate. T-16 in rework.

Superseded most of the 2026-09-06 stop note below; that note was already stale when read
(it said T-18's F1 fix was uncommitted — it was committed, as `e1dc0e3` and `71789b7`).

**Evan answered eight banked decisions by decision form** (`media-list-2026-09-06`, submitted
2026-09-07 03:45 UTC, artifact `a0b2f1ad`), **A on all eight**. Recorded as GA-7 (T-18) and
GA-8 (T-16). What they settle, so nobody re-asks:

| | His answer |
| --- | --- |
| Run to accept vs. show first | **Run both straight through to his accept gate**; merge is unattended in this shop |
| Order | **T-18 first, then T-16** |
| Push the unpushed commits | **Push now** — held pending his word in-session, still unpushed |
| Name + email in published history | **Leave both alone.** No rewrite, no force-push. Do not raise again |
| IGDB asked about every CSV row (~251s/1000 rows) | **Keep it.** The mis-declared-row rescue is worth the four minutes |
| Load-sensitive momentum test | **Leave it, documented.** It tells the truth; red on a loaded machine is information |
| The 14 fixture rows | **Wipe them** — held pending his word; wiping after T-16 lands costs nothing |
| Onboarding "about" step | **Skip.** Recorded skipped 2026-09-07; never raise again |

### T-18 — merged, awaiting HIS accept

`main` @ `44cde79`. Two review rounds, then an independent live verify. Round 2's own F1 fix
introduced F4 — on a rapid same-path double-navigation, two renders both reach the mount branch
and the second overwrote `mounted` without running the first's `cleanup`. Reproduced with an
instrumented bundle, not argued. **The dispatcher landed the one-line fix rather than deferring
it** (`23f2b98`): it is this ticket's own regression, and T-16 is adding views right now, which
is when a dropped `cleanup` stops being theoretical.

**App-wide behaviour change:** a view is dismissed when the user LEAVES it, not when its
replacement is ready. T-15's import stream now cancels at the click rather than seconds later.
A full page reload deliberately does NOT restore the search — recorded choice, not an oversight.

Verified live against a byte-copy of the real database (`MEDIA_LIST_DB` redirected): all six ACs
by hand with real TMDB/IGDB calls, six-screen navigation sanity pass, rapid-fire tab cycling left
exactly one `<main>` in the DOM. Owner DB mtime identical before and after.
pytest **134 passed, 1 skipped** · browser **54 passed** chromium + firefox.

### T-16 — in rework after a LOOPBACK worth reading

**The migration is SOUND and must not be reopened.** The reviewer re-derived the builder's
interrupt-safety claim with an *external* `SIGKILL` (the builder used in-process `os._exit`):
30 runs, 30 kills, 0 failures; `PRAGMA user_version` proven transactional. `_rebuild_titles`
is settled.

Four findings sent it back. **F1 (HIGH) is the one to remember:** `schema.sql:14`, `db.py:30-32`
and the new `kb/wiki/lessons.md` entry all claimed that adding a COLUMN to `schema.sql` is
self-applying. It is not — proven live (`'pages' in table -> False`). T-16's `isbn` only landed
because the CONSTRAINT change forced a rebuild, which makes the wrong lesson very easy to draw
from this ticket. F2/F3/F4 are one cluster: the frontend was wired for books in `kinds.js` and
nowhere else — no author on the title page, no `book` chip on queue/seen/wheel, and books wear
anime's colour on the wheel.

~~`frontend/src/views/add.js:112` placeholder is fenced out of T-16's rework.~~ **Done** — applied
at the merge (`8dc731d`), along with `home.js`'s empty-list copy, which named the same four kinds
in a second place no review had listed. With `data/` wiped, that empty screen is the first thing
the owner sees.

### New standing check — the tenth green-but-empty test

In a hash router, `toHaveURL` is not evidence a screen was ever mounted: the hash updates the
address bar before the router resolves anything. Assert on something only the destination
renders. Written up in `kb/wiki/lessons.md`; caught by the build seat, not review.

**Recorded absence:** this repo has NO lint or typecheck of any kind — no ESLint, Prettier,
tsconfig, ruff, flake8, pre-commit. The stage contract names them; they do not exist here.
Never read "lint green" into a preflight pass.

---

## STOPPED 2026-09-06 ~00:30, mid-flight — read this first

Three tickets shipped and merged today (T-13 runner · T-14 two engines · T-15 large-CSV import),
then T-17 (add-tab preview). **Nothing is half-merged. `main` is clean and green: 134 pytest
passed, working tree clean.** All in-flight work is safe on its own branch.

| Ticket | State | Branch | What is left |
| --- | --- | --- | --- |
| **T-16 books** | at `auto-review`, **built and independently verified**, NOT merged | `t16-books` @ `0a1d24b` | needs a review round, then merge + the two cross-ticket patches below |
| **T-18 back button** | at `build`, **rework attempt 2 INTERRUPTED mid-flight** | `t18-back-keeps-search` @ `912b8fe` | round-1 work is committed; the F1 router-race fix was *in progress and is NOT committed* — restart it from `.autodev/evidence/T-18/auto-review.md` |

### T-16 is proven where it counts
The migration was re-run by the dispatching session on a copy of the owner's database: 15 rows in,
15 out, **zero drift on every pre-existing column**, the `seen` row keeps its stars and review, the
NULL poster stays NULL. Interrupt safety checked at **25 random kill points — 25/25 reopened with
every row, 0 damaged**. His original is byte-identical (sha256 `5f122ead…`).

### ~~Two patches T-16 deliberately did NOT make~~ — BOTH SHIPPED 2026-09-07
1. ~~`views/title.js::facts()` never renders a book's author.~~ Fixed in T-16's rework, with a
   browser test that proves the Author fact actually renders (it times out against the pre-fix code).
2. ~~`add.js` placeholder.~~ Applied at the merge, plus `main.js`'s `media_type` comment and
   `home.js`'s empty-state copy.

### T-18's open finding, reproduced and not yet fixed
`router.js`'s `render()` awaits the incoming view **before** dismissing the outgoing one, and
`addView()` is the only synchronous view — so a second Add mount reads the stash before the first
mount's `cleanup()` writes it. Probe: search "dune", bounce through a Queue with `/api/titles`
delayed 1.5s, and `#q` comes back **empty**. Full findings in `.autodev/evidence/T-18/auto-review.md`.

### Also today, on main
- **`.gitignore` now ignores `*.csv`**, not just `media-list-export*.csv`. The old rule was
  name-based, so `my-list.csv` or `backup.csv` would have been committed to a public repo carrying
  his titles, `why` notes and reviews. Nothing was ever exposed.
- Both test harnesses now rebuild the frontend when the bundle is **stale**, not only when missing.
- **`main` is 12 commits ahead of `origin` and NOT pushed** — the owner's standing rule is
  "do not push without asking", and his earlier "push it all" covered that batch only.

## What is NOT done, and is genuinely open

- **Local `main` is well ahead of `origin/main` and is NOT pushed.** origin sits at the
  18 commits published 2026-09-05; T-13 and T-15 landed locally on top. The standing directive
  ("do not push without asking") holds — the owner's go-ahead GA-3 covered his spec and accept
  gates, not publishing to a public repo. The credential
  audit is in `kb/notes/handoff.md` §10 — all four API keys are absent from every commit, and
  `.env`/`data/`/`*.db` have never been tracked. Two residual identifiers (the name inside two
  commit messages, and the author email on every commit) are permanent unless the owner
  chooses a history rewrite.
- **Two engines by decision, not three (T-14 — SHIPPED).** The owner chose it, verbatim:
  *"Go with (a), two engines is fine."* AC2 amended in `.autodev/specs/T-14.md`. Chromium and
  Firefox pass 20/20 via `scripts/test.sh --browsers`. **WebKit cannot launch on this machine**: it needs
  `libjxl.so.0.8` and `libbacktrace.so.0`, and Ubuntu 24.04 ships only `libjxl0.7` with no
  `libbacktrace` package at all — so `playwright install-deps` would not fix it either. The
  webkit project stays wired in and the command **fails loudly** rather than skipping, so the
  gap stays visible rather than becoming two engines quietly called three. Playwright's WebKit
  on Linux is not Safari in any case — the signal given up here was always limited.
- ~~Large-CSV import is untested.~~ **Done 2026-09-05 (T-15).** Bounded concurrency plus a
  per-run lookup cache: 1000 rows over 50 distinct titles now costs 100 searches, not 2000.
  Atomicity is unchanged and proved *structurally* — no `await` inside any `with connection()`
  block, so a cancellation cannot land mid-transaction.
  **Expect ~251 seconds for a 1000-row preview, not the 0.75s the loop test reports.** IGDB is
  asked about every row regardless of declared kind and paces at 4/s. Skipping IGDB for
  `movie`/`anime`/`live-action` rows would be ~5× — at the cost of the "nothing of kind X
  matched" recovery path. **An open design decision for the owner**, with a test that stops it
  being taken silently (trade-off table in `kb/notes/handoff.md`).
- **The momentum browser test is load-sensitive (open, proposed as its own ticket).**
  `tests/browser/wall.spec.js:98` fails on a saturated machine — measured: load 19.98 on 20 cores
  → red on both engines and a 1.7m suite; load ~10 → green in 32.7s. The mechanism is
  `carousel.js:164`, `velocity = … * (16 / dt)`: when the host stretches the gap between the last
  `pointermove` and `pointerup`, velocity falls under `MIN_VELOCITY` and a flick genuinely is a
  slow drag. The test is honest; what it measures depends on the scheduler. Making it
  deterministic means not driving the real gesture path — the owner's call.
- **The list is ENTIRELY test data — the owner has added nothing yet.** Corrected by him
  2026-09-05: *"I didn't do anything yet. There's no 14 rows."* All 14 rows in
  `data/media-list.db` are build fixtures from T-4/T-9/T-10, seeded the day they were created,
  that happen to be real titles: The Thing · Perfect Blue · Hollow Knight (5★) · Cowboy Bebop ·
  Breaking Bad · Andor · Arrival · The Truman Show · Super Mario 64 · NieR: Automata (4★, the one
  `seen` row) · JUJUTSU KAISEN · Akira · Outer Wilds · Attack on Titan.
  **Treat them as disposable**, and do not describe them as his watchlist. `rm -rf data && ./start.sh`
  rebuilds an empty database in ~9s. His real list is still to come — he planned to generate one
  with a chatbot using the README prompt.
- `pipelines.wiring` doctor warn is the unused `feature-regulated` pipeline — same benign
  warn as repo-tour.
