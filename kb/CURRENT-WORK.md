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
- **Test data on the list.** Akira, Outer Wilds and Attack on Titan were added by import
  tests; NieR: Automata and Hollow Knight carry test ratings. Real titles, the owner's to curate.
- `pipelines.wiring` doctor warn is the unused `feature-regulated` pipeline — same benign
  warn as repo-tour.
