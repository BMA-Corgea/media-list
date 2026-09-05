# media-list — handoff

**Date:** 2026-09-05 · **Branch:** `main` (18 commits, **pushed**) · **HEAD:** `e31c84d`
**Remote:** `https://github.com/BMA-Corgea/media-list.git` — public, `main` is up to date
(local and origin are identical; nothing to push)
**Restore point:** every unit of work is its own commit; `git reset --hard <hash>` is the undo.
**Working tree:** clean. **No servers left running.**

---

## 1. Mission & standing directive

Build the owner a private watchlist for anime, films, live-action and video games that is **more
fun than the spreadsheet it replaces**. Their framing, recorded in the T-1 goal doc: the
spreadsheet is not failing at storage, it is failing at **retrieval and desire**. Cover art,
the carousel and the wheel are therefore *the requirement*, not decoration — a ticket that
ships correct data behind a dull surface has missed the objective.

**Instructions in force (do not violate):**

- **Full autonomy on the T-1 branch.** The owner, verbatim: *"Just loop through it. Go ahead and
  build it. I don't need to approve anything. Get through all the tickets"* — recorded as
  grant `G-1` and go-ahead `GA-1` in `.autodev/`. **That branch is now complete, so the
  go-ahead is spent.** New work needs a fresh yes.
- **Do not push without asking.** The repo is public; the owner has never said to push.
- **Loopback only.** `127.0.0.1` is a decision, not an oversight. Phone access, if ever
  wanted, goes through the GUTS Bridge — not a wider bind.
- **The app is public; the list is not.** Database, cached title artwork and CSV exports never
  enter git.
- **Pexels is never a source of title artwork.** Ambient chrome only.

---

## 2. How to verify

```bash
cd "/home/corgea/Desktop/Coding Projects/media-list"
./start.sh                      # → http://127.0.0.1:7799
```

Cold boot from a **fresh clone** takes ~9s (creates `.venv`, installs deps, builds the
frontend, creates the database). Runtime: **Python 3.12.3** in `./.venv`, **Node v22.22.2**.
Port **7799** is reserved for this project in `../PROJECT_PORTS.md`; `start.sh` deliberately
**refuses** to kill whatever holds the port rather than fighting for it.

There is **no test suite** (see §4). Verification is by real commands. The load-bearing ones:

```bash
curl -s localhost:7799/api/health                       # 200 + which sources have credentials
curl -s "localhost:7799/api/search?q=cowboy%20bebop"    # 1998 anime, 2021 live-action, 2001 film
curl -s --path-as-is 'localhost:7799/../../.env'        # MUST be the SPA shell, MUST NOT leak
rm -rf data && ./start.sh                               # database must rebuild itself
```

Browser checks used Playwright from a sibling project (there is no local install):
`/home/corgea/Desktop/Coding Projects/GLP-Strong-App/node_modules/.pnpm/playwright@1.62.1/node_modules/playwright/index.mjs`

---

## 3. Standing checks — each one caught a real defect

Run the relevant one when you touch the matching area. These are not ceremony; every row
below exists because it found something.

| Check | Why it exists |
| --- | --- |
| SPA traversal payloads (`../../.env`) whenever routes or static mounts change | T-2's fallback served the **real `.env` with live API keys** to `curl --path-as-is` |
| Grep the built bundle for a string unique to new code | `npm run build` reported ✓ while a module was **never imported** |
| Colour-literal grep across `frontend/src/skins/base.css` | Keeps every surface re-skinnable by a skin written before it |
| Chi-square **+ a negative control** if `pickIndex` changes | A max-deviation bound was statistically naive and failed a *correct* picker |
| Assert **computed** styles, never stylesheet text | An undefined CSS custom property fails silently and looks deliberate |
| `git check-ignore` on `data/`, `*.db`, `.env` | The privacy boundary is the whole point |

---

## 4. Quality baseline — known, not regressions

- **No automated test runner exists.** Every check was a real command recorded in
  `.autodev/evidence/T-*/`. Nothing is frozen in CI. **Hold the bar at: no new failures
  against the commands in §2/§3.**
- **`/autodev:doctor` → 18/19 pass, 1 warn.** The warn is `pipelines.wiring`: the unused
  `feature-regulated` pipeline has no `compliance-officer` role. Benign; `repo-tour` has the
  identical warn.
- **Chromium only.** No second browser engine has ever run this app.

---

## 5. ✅ Complete

| Commit | Ticket | What landed |
| --- | --- | --- |
| `5090792` | — | README (with the published CSV contract), MIT licence, the `.gitignore` privacy boundary |
| `66ca620` | **T-2** | FastAPI on 7799, self-creating SQLite, repo-tour's skin contract ported (base + `nocturne` + `paperback`) |
| `f3e435c` | — | Factory state: direction T-1 and the ten-ticket set |
| `5e0aeb2` | **T-3** | TMDB + AniList + IGDB clients, content-addressed artwork cache |
| `37b7ab3` | **T-4** | Search-and-pick add flow; the minimal client router |
| `1071c0b`, `0697ce8` | — | IGDB credentials arrived; T-3's deferred live tests run |
| `0cc2268` | **T-5** | The coverflow wall — drag, throw, buttons, keyboard |
| `7c6842c` | **T-6** | Title page, per-kind facts and links, editable `why` |
| `7eeef2d` | **T-7** | One global queue, drag reorder, kind filters |
| `b314c26` | **T-8** | The wheel — provably uniform picker, long decelerating spin |
| `b39aa82` | **T-9** | Star rating and the browsable Seen archive |
| `860d727` | **T-10** | CSV export + the resolver import (atomic commit) |
| `9d9d697` | **T-11** | Pexels ambient chrome with full attribution |
| `e421a66` | — | Branch close; `kb/CURRENT-WORK.md` rewritten as the finished-state record |

**All 11 AutoDev tickets are `complete`.** `/autodev:status` confirms 11/11.

---

## 6. Established patterns — keep new code consistent with these

- **Skins.** One CSS file at `frontend/src/skins/<name>.css`, every rule scoped under
  `:root[data-theme="<name>"]`, plus one row in `frontend/src/skins.js`. `base.css` owns the
  bare `:root` and carries tokens **and** the component layer — which is why an alternate can
  be 70 lines of token overrides and still restyle surfaces written after it. **No component
  CSS in a view file, ever.**
- **Text over photographs** uses `--ink-over-art`, not `--ink` (near-black over a dark still
  is unreadable) and not `#fff` (that breaks the no-literals rule).
- **Queue positions are gap-tolerant.** Append `MAX+10`, prepend `MIN−10`, insert at the
  midpoint, renumber to multiples of 10 only when no integer fits. **Never renumber casually.**
- **Reordering takes neighbour *ids*, never an index** — an index is meaningless in a filtered
  view, and this is what makes filtered reordering safe by construction.
- **A stored TMDB title must persist its `media_type`.** Movie and TV ids are separate
  namespaces; `/api/details/tmdb/<id>` refuses without it rather than guessing.
- **`PATCH /api/titles/{id}` is sparse on purpose** — add fields there rather than growing new
  endpoints.
- **The kind→verb map lives only in `frontend/src/kinds.js`** so no two screens can disagree
  that a game is *played*.
- **Empty means NULL**, not `""` — so "has a `why`" stays one truthiness test everywhere.
- **Pointer gestures:** capture the pressed element at `pointerdown` (`setPointerCapture`
  retargets later events), and ignore movement under a 6px threshold so a drag never fires a
  click.
- **Concurrency belongs in a FETCH phase, never in a write loop.** `import_commit` resolves
  every record first, outside any transaction, and only then opens one transaction on one
  connection and writes sequentially. Two things depend on that loop staying sequential and
  single-connection: the per-row duplicate `SELECT` reads that connection's own uncommitted
  inserts, and `top += 10` walks queue positions forward in file order. `asyncio.gather`
  preserving its input order is what lets the fetch phase be concurrent without disturbing
  either (T-15).
- **Every outbound call takes a rate-limit slot.** `backend/sources/base.py` holds one
  `RateLimit` per upstream carrying that upstream's own published numbers — requests/second
  AND open requests, because a concurrency cap is not a rate. A new source, or a new call site
  in an existing one, gets a slot or it is not bounded at all (T-15 AC6).

---

## 7. ⬜ Remaining — ordered, each concrete enough to start

1. **~~Push to GitHub~~ — done 2026-09-05 by another session, at the owner's request.**
   `c768c31` was the first push. Audited afterwards from this session: **all four credential
   values are absent from every commit in the pushed history**, and `.env` / `data/` / `*.db`
   have never been tracked. See §10 for what the push did leave exposed.

2. **Clean the test data off the list** *(the owner's call — these are real titles, not junk)*
   Added by import tests: **Akira**, **Outer Wilds**, **Attack on Titan**.
   Carrying test ratings: **Hollow Knight** (5★, back in the queue from an un-watch test),
   **NieR: Automata** (4★, the only `seen` row, with a test review).
   Removable in the UI, or: `DELETE FROM titles WHERE title IN (...)`.

3. **An automated test runner** *(the biggest real gap)*
   Behaviour is now stable enough to freeze. `pytest` for the API — star validation, the
   reorder arithmetic including gap exhaustion, CSV round-trip, and import atomicity are all
   already written as ad-hoc scripts in the evidence files and mostly liftable. The
   Playwright checks are the second layer, but note the dependency is borrowed from
   GLP-Strong-App and would need installing locally.

4. **Second browser engine.** Firefox/WebKit have never run this. The carousel and the wheel
   are the risky surfaces (Pointer Events, 3D transforms, CSS transitions).

5. **~~Large-CSV import~~ — done 2026-09-05 (T-15).** A 1000-row generated CSV now drives
   the resolver in `tests/test_import_scale.py`, with a wall-clock ceiling the suite enforces
   (`CEILING_SECONDS`). 4.95s → 0.76s on 1000 distinct titles; a repeated list is 0.07s and
   makes 95% fewer outbound requests. `/api/import/preview` streams NDJSON progress instead of
   returning one blob at the end. The insert loop did not move, and atomicity is proven at 500
   rows with the sabotage halfway through the batch.

6. **The owner's actual list.** They planned to generate one with ChatGPT using the prompt in
   `README.md`. When it arrives: paste into `#/transfer` → Preview → settle the ambiguous
   rows → Import.

---

## 8. Artifact pointers

| Path | What is in it |
| --- | --- |
| `.autodev/evidence/T-*/` | **Most important.** Per-ticket evidence with real command output and screenshots. **Local only** — `.autodev/` was untracked and gitignored on 2026-09-05 for the public repo. Still on disk, still read by the tracker; never `git add -f` it. |
| `.autodev/specs/T-*.md` | Acceptance criteria per ticket, written to be failable |
| `kb/CURRENT-WORK.md` | Finished-state summary and the standing checks |
| `README.md` | The **published** CSV contract — the owner was told to rely on it, so it must not drift from `backend/csvio.py` |
| `../PROJECT_PORTS.md` | The port registry; `7799`/`5799` reserved here |
| `../repo-tour/src/skins.ts` | Where the skin contract came from |

---

## 9. Gotchas

- **`origin/main` does not exist locally.** `git log origin/main..HEAD` prints `0` — that is
  git failing to resolve a ref, **not** "nothing to push". Use `git rev-list --count HEAD`.
- **`pkill -f "uvicorn ..."` kills your own shell** — the pattern matches the shell's own
  command line. Get the PID from `ss -ltnp` instead.
- **`.env` was created before the IGDB block was added to `.env.example`**, so it did not
  inherit those keys. If a credential seems absent, check `.env` actually has the line.
- **`tracker.mjs respec` is direction-tickets only.** A work ticket's spec is earned at
  `refine`; changing one means `rewind --to refine`.
- **On-behalf gate clearance needs the grant/go-ahead id as the ref** —
  `agent:claude(on-behalf:<owner>,GA-1)`, not a session id. **`GA-1` is now spent.**
- **An epic-scoped grant seals when its epic completes.** `G-1` covered only T-1 within
  minutes of being issued, because a `direction` ticket completes at `dir-route`.
- Playwright is **borrowed** from GLP-Strong-App and is not a dependency of this project.
- Do not commit `data/`, `.env`, or `frontend/dist`.

---

## 10. Public-repo exposure — audited 2026-09-05, three items left

`main` was pushed on 2026-09-05 (`c768c31`, by another session at the owner's request), which
made the **entire 16-commit history public at once**. Audited from this session afterwards:

**Clean:**
- All four credential values (`TMDB_API_KEY`, `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET`,
  `PEXELS_API_KEY`) are **absent from every commit** — checked by grepping each real value
  across every blob in `git rev-list --all`.
- `.env`, `data/` and `*.db` have **never** been tracked, at HEAD or in any commit.

**Still exposed — each needs a decision:**

1. **`LICENSE` said `Copyright (c) 2026 <name>`. — RESOLVED.** It now reads
   **`Copyright (c) 2026 GIMS Technologies`**, which is the owner's own answer, given on
   2026-09-05 and applied in `e31c84d`. (I had provisionally put the GitHub org there;
   that was a placeholder pending exactly this decision.) **Use "GIMS Technologies" as the
   copyright holder anywhere else one is needed.**
2. **Two commit messages still contain the name** — both inside `860d727` (T-10). Fixing
   these means **rewriting published history and force-pushing**, which is destructive and is
   the owner's call alone. Do not do it unprompted.
3. **Every commit is authored `Corgea <blackmapartistry@gmail.com>`.** The email address is
   on all 16 public commits. This is the account's own git identity rather than anything this
   project chose, and it is already visible as the repo owner — but if the intent is "no
   personal identifiers in public repos", it is the largest remaining one, and it too would
   need a history rewrite plus a `git config user.email` change going forward.

**The honest framing:** items 2 and 3 are permanent in the published history unless the owner
chooses a rewrite. Fixing them at HEAD reduces visibility, not exposure.
