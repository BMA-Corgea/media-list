# T-2 — Review

Three findings, all in code written by this ticket. All fixed and re-verified before the
stage passed.

## 1. Path traversal in the SPA fallback — **served the real `.env`, keys and all**

`candidate = dist / full_path` then `FileResponse(candidate)`. Browsers normalise `..` out
of a URL, so this looked fine in every browser test. Non-browser clients do not:

```
curl --path-as-is 'http://127.0.0.1:7799/../../.env'   ->  200, 762 bytes
```

The response was **byte-identical to `.env`** (sha256 compared against both `.env` and
`.env.example` to be sure which file it was), carrying non-empty `TMDB_API_KEY` and
`PEXELS_API_KEY`. `/etc/passwd` happened to miss only because `../../../` from `dist/` lands
in `Coding Projects/etc/`, which does not exist — luck, not a control.

Scope of the exposure: the listener is loopback-only and nothing left this machine, so the
keys were reachable by a local process, not by the internet. No rotation needed, but the
class of bug is real and it was a leak, not a theoretical one.

**Fix:** resolve the candidate and require containment.

```python
candidate = (dist / full_path).resolve()
inside = candidate == dist_root or dist_root in candidate.parents
if full_path and inside and candidate.is_file():
```

`dist_root` is resolved once at app construction, so symlinks and a relative `dist` cannot
widen what is reachable either.

**Re-verified:** `../../.env`, `../../../../../etc/passwd`, `../../requirements.txt`,
`../../backend/config.py` and `../../.git/config` now all return the SPA shell. Legitimate
paths unaffected — hashed CSS 200 text/css, `/api/health` 200 json, `/` 200 html.

## 2. `bootstrap()` leaked a connection on every call

`with sqlite3.connect(...) as conn` manages the **transaction**, not the connection — it
never closes. One boot leaks one handle, which is nearly harmless; tests and reloaders that
bootstrap repeatedly accumulate them.

**Fix:** explicit `try/finally: conn.close()`.
**Re-verified:** 50 consecutive `bootstrap()` calls, open fds counted from `/proc/self/fd`
before and after — **4 → 4, zero leaked**.

## 3. WAL sidecars were covered only by the `data/` rule

`PRAGMA journal_mode = WAL` produces `-wal` and `-shm` files holding committed rows not yet
checkpointed — as revealing as the database. `.gitignore` listed `*.db-journal` but not the
WAL pair, so they were protected only by living under `data/`. Point `MEDIA_LIST_DB`
somewhere else and the privacy boundary silently thins.

**Fix:** `*.db-wal` and `*.db-shm` ignored on their own merit.
**Re-verified:** `git check-ignore -v` matches both at `.gitignore:9` and `:10`.

## Considered and deliberately left alone

- **A connection per query.** `query()`/`execute()` open and close per call. At one user and
  a few hundred rows that is cheaper than a pool and has no correctness cost. Revisit if
  T-10's bulk import is slow — that ticket will measure it rather than assume.
- **`bootstrap()` runs at import time**, so importing `backend.main` creates the database.
  That is the stated design ("opening the app is what builds it"), not an accident, and it
  is what makes AC2 true.
- **`start.sh` parses `.env` with grep/cut**, which would mishandle quoted values or inline
  comments. The only keys it reads are host and port; the app itself uses `python-dotenv`
  and parses properly. Not worth a parser here.
