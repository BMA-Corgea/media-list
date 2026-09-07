# CURRENT WORK — media-list

## The branch is finished

**T-1 and all ten child tickets are complete** (2026-09-04). The app runs, and everything
T-1's success shape promised is built and proven.

| | |
| --- | --- |
| Run it | `./start.sh` → `http://127.0.0.1:7799` |
| Test it | `scripts/test.sh` — the whole suite, exits non-zero on failure (`--live` opts into real network calls) |
| Cold boot | ~9s from a fresh clone: venv, deps, frontend build, database, serving |
| Screens | wall · queue · wheel · seen · add · import |
| Sources | TMDB + AniList (screen), IGDB (games), Pexels (chrome only) |
| Repo | github.com/BMA-Corgea/media-list — **public and pushed**; copyright holder is **GIMS Technologies** |

## Standing checks — cheap, and each one caught something real

The first four rows are frozen into `scripts/test.sh` as of T-13 — no longer tribal
knowledge in an evidence file, an actual command that exits non-zero. Row by row:
`tests/test_privacy_boundary.py` (rows 1–2), `tests/test_bundle.py` (row 3),
`tests/test_csv_roundtrip.py` and `tests/test_import_atomicity.py` (row 4).
The last two need a real browser to assert against and are T-14's job.

| Check | Why it exists |
| --- | --- |
| `git check-ignore` on `data/`, `*.db`, `.env` | The privacy boundary is the point of the project |
| SPA traversal payloads whenever routes or static mounts change — percent-encoded (`%2e%2e`), and the route called directly with a raw `../../.env`, because an HTTP client collapses a plain `../` before the app sees it | T-2's fallback served the real `.env` with live API keys |
| Grep the built bundle for a string unique to new code | A green Vite build did not catch an unimported module |
| CSV round-trip + import atomicity against the README contract | T-10's resolver defects (wrong-kind match, an all-or-nothing commit) |
| Colour-literal grep across `base.css` | Keeps every surface re-skinnable by a skin written before it |
| Chi-square + negative control if `pickIndex` changes | A max-deviation bound was statistically naive and failed a correct picker |
| Assert **computed** styles, not stylesheet text | An undefined CSS custom property fails silently and looks deliberate |

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

`frontend/src/views/add.js:112` (the "film, series, anime or game" placeholder) is fenced OUT of
T-16's rework to avoid a conflict with T-18's `add.js` changes. **The merge owner owns that line.**

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

### Two patches T-16 deliberately did NOT make (T-18 owned those files)
Apply after T-18 merges:
1. **`views/title.js::facts()` branches `game` vs everything-else**, so a book takes the
   screen-title branch and **never renders its author**. `detail.author` / `detail.pages` are
   already stored. Exact patch in `.autodev/handoffs/T-16.md`.
2. `frontend/src/views/add.js:112` placeholder still says "film, series, anime or game" — needs
   "book". Plus an optional `main.js` comment.

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
