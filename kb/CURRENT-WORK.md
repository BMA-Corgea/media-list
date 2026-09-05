# CURRENT WORK — media-list

## The branch is finished

**T-1 and all ten child tickets are complete** (2026-09-04). The app runs, and everything
T-1's success shape promised is built and proven.

| | |
| --- | --- |
| Run it | `./start.sh` → `http://127.0.0.1:7799` |
| Cold boot | ~9s from a fresh clone: venv, deps, frontend build, database, serving |
| Screens | wall · queue · wheel · seen · add · import |
| Sources | TMDB + AniList (screen), IGDB (games), Pexels (chrome only) |
| Repo | github.com/BMA-Corgea/media-list — **committed locally, never pushed** |

## Standing checks — cheap, and each one caught something real

| Check | Why it exists |
| --- | --- |
| `git check-ignore` on `data/`, `*.db`, `.env` | The privacy boundary is the point of the project |
| SPA traversal payloads (`../../.env`) whenever routes or static mounts change | T-2's fallback served the real `.env` with live API keys |
| Grep the built bundle for a string unique to new code | A green Vite build did not catch an unimported module |
| Colour-literal grep across `base.css` | Keeps every surface re-skinnable by a skin written before it |
| Chi-square + negative control if `pickIndex` changes | A max-deviation bound was statistically naive and failed a correct picker |
| Assert **computed** styles, not stylesheet text | An undefined CSS custom property fails silently and looks deliberate |

## What is NOT done, and is genuinely open

- **Never pushed.** 14 commits sit on local `main`. The GitHub repo is public and empty.
- **Chromium only.** Every browser test used one engine.
- **No automated test runner.** Every check was a real command, but they live in evidence
  documents rather than in something CI could run. Worth a ticket now that behaviour is
  stable enough to be worth freezing.
- **Large-CSV import is untested.** A chatbot list of thousands of rows would make the
  per-row search dominate the preview.
- **Test data on the list.** Akira, Outer Wilds and Attack on Titan were added by import
  tests; NieR: Automata and Hollow Knight carry test ratings. Real titles, Evan's to curate.
- `pipelines.wiring` doctor warn is the unused `feature-regulated` pipeline — same benign
  warn as repo-tour.
