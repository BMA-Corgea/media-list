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

The first four rows are frozen into `scripts/test.sh` as of T-13 (`tests/test_privacy_boundary.py`,
`tests/test_bundle.py`) — no longer tribal knowledge in an evidence file, an actual command
that exits non-zero. The last two need a real browser to assert against and are T-14's job.

| Check | Why it exists |
| --- | --- |
| `git check-ignore` on `data/`, `*.db`, `.env` | The privacy boundary is the point of the project |
| SPA traversal payloads (`../../.env`) whenever routes or static mounts change | T-2's fallback served the real `.env` with live API keys |
| Grep the built bundle for a string unique to new code | A green Vite build did not catch an unimported module |
| CSV round-trip + import atomicity against the README contract | T-10's resolver defects (wrong-kind match, an all-or-nothing commit) |
| Colour-literal grep across `base.css` | Keeps every surface re-skinnable by a skin written before it |
| Chi-square + negative control if `pickIndex` changes | A max-deviation bound was statistically naive and failed a correct picker |
| Assert **computed** styles, not stylesheet text | An undefined CSS custom property fails silently and looks deliberate |

## What is NOT done, and is genuinely open

- ~~Never pushed.~~ **Pushed 2026-09-05**; `main` is public at 18 commits. The credential
  audit is in `kb/notes/handoff.md` §10 — all four API keys are absent from every commit, and
  `.env`/`data/`/`*.db` have never been tracked. Two residual identifiers (the name inside two
  commit messages, and the author email on every commit) are permanent unless the owner
  chooses a history rewrite.
- **Chromium only.** Every browser test used one engine — no second engine runs yet
  (`scripts/test.sh` is the harness T-14 plugs Firefox/WebKit Playwright runs into).
- **Large-CSV import is untested.** A chatbot list of thousands of rows would make the
  per-row search dominate the preview (T-15's bound test lands in `scripts/test.sh`).
- **Test data on the list.** Akira, Outer Wilds and Attack on Titan were added by import
  tests; NieR: Automata and Hollow Knight carry test ratings. Real titles, the owner's to curate.
- `pipelines.wiring` doctor warn is the unused `feature-regulated` pipeline — same benign
  warn as repo-tour.
