# T-2 — Build evidence

Every acceptance criterion was run, not reasoned about. Real commands, real output.

| AC | Claim | How it was proven | Result |
| --- | --- | --- | --- |
| AC1 | Boots on 7799; `/api/health` returns version + resolved DB path | `curl` against live uvicorn | **200**; `version 0.1.0`, absolute `db_path`, `db_exists: true`, and a credential map (`tmdb: true, igdb: false, pexels: true`) |
| AC2 | The database creates itself | `rm -rf data` then boot | `data/` confirmed absent first; bootstrap returned the path; file existed at 4096 bytes |
| AC3 | Bootstrap is idempotent | insert a row → new process → re-run bootstrap → read back | row survived, count still 1 |
| AC4 | Schema complete for the whole branch | `PRAGMA table_info` diffed against the spec's column list | 21/21 columns, **0 missing**; 4 indexes; `user_version 1`; `imdb_id` notnull flag **0 — nullable, as games require** |
| AC4b | The constraints actually bite | four deliberately bad inserts | `kind='book'`, `source='rawg'`, `stars=9` and a duplicate `(source, source_id)` each refused with `IntegrityError`; a game with NULL `imdb_id` accepted |
| AC5 | Build served; SPA fallback excludes `/api` and `/art` | six-path `curl` sweep | `/` and `/some/deep/route` → 200 html; `/api/health` → 200 **json**; `/api/nope` → 404 **json**; `/art/nothing.jpg` → 404; hashed CSS → 200 text/css |
| AC6 | A skin costs one CSS file + one registry row, nothing else | added a throwaway `_probe` skin, rebuilt, drove the real switcher in Chromium, reverted | option appeared; `body` background became `rgb(255,0,255)`; revert left **zero residue** in source or bundle |
| AC7 | Applies before first paint — no flash | **stylesheet held 600ms by request interception**, DOM inspected mid-flight | `readyState: interactive`, `data-theme: "nocturne"`, **`styleSheets.length: 0`** — the attribute was in place while *no stylesheet had been applied at all*, so CSS could not have painted another palette |
| AC8 | Nothing private is committable | `git status --porcelain`, `git check-ignore`, dry `git add -A` after a boot that wrote the DB | `data/media-list.db`, `.env`, `frontend/dist` all ignored; dry add surfaced no `.env`, `.db` or `data/` path |

## Skins shipped

`nocturne` (blue-black ground, projector amber) and `paperback` (cream paper, faded stamp
red), over a system-following base. Chosen so the contract is proven in **both** brightnesses
— measured body backgrounds `rgb(11,13,20)` and `rgb(239,233,220)`, with `system` resolving
to `rgb(244,242,239)`. Screenshots beside this file.

## Zero application errors

Chromium reported no `pageerror` and no console errors across every run. An earlier probe
did throw three TypeErrors — that was the **test harness** reading `document.documentElement`
inside an init script before the document element exists, not the app. The probe was
rewritten; the final run is clean.

## Honest gaps

- **Chromium only.** No second browser was tested.
- **`start.sh`'s own cold path is only partly exercised** — the venv and `npm install` legs
  ran during this build, but the script end-to-end is the verify stage's job.
- **No automated test suite.** Every check above was a real command, but they live in this
  document rather than in a runner. Worth its own ticket once there is behaviour stable
  enough to be worth freezing; nothing here is yet.
