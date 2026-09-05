# T-10 — CSV export and the resolver import: build evidence

## Two defects found in this ticket's own design

### 1. A game exported with **no id at all**

The README's export columns had `tmdb_id` but no `igdb_id`. A game's id is an IGDB id, and
writing it under a `tmdb_id` header would be a lie that survives the round trip — so it was
written blank, which meant every game had to be **re-resolved by search** on the way back in.
That makes AC2 approximate rather than exact, and a re-resolve can land on a different entry.

**Fix:** `igdb_id` added to the export contract, and `README.md` updated to match, since that
document is what Evan has been told to rely on. The *starter* format he pastes into a chatbot
(`title,year,kind,why`) is untouched.

### 2. The resolver nearly imported a **video game as an anime**

Scoring `Cowboy Bebop, 1998, anime`:

```
  168.33  tmdb  1998  anime        Cowboy Bebop
  140.00  igdb  1998  game         Cowboy Bebop      <- there is a 1998 Cowboy Bebop GAME
   52.80  tmdb  2021  live-action  Cowboy Bebop
```

Same title, same year, different medium — 28 points apart, close enough that any small weight
change flips it. The row **said** `anime`.

**Fix:** a declared `kind` is now a **filter, not a preference**. Candidates of another kind
are not answers to that row at all. After it, every row of the README's own starter CSV
resolves correctly.

### 3. The import button promised a number the commit would not deliver

Picking a different candidate by hand marked the row "ready" without re-checking whether *that*
candidate was already on the list. The button said **"Import 3"**, the commit did **2**. The
commit was right; the promise was wrong. Preview now returns the existing key set, and picking
a duplicate flips the row to *"already on your list"* immediately.

## Acceptance criteria

| AC | Result |
| --- | --- |
| AC1 export | Header exactly the README's columns; a game row carries `igdb_id` and blank `tmdb_id`/`imdb_id`. |
| **AC2 round-trip** | Export → preview → commit: **11 rows in, 11 rows out, `added: 0, skipped: 11`**, and a SHA-256 fingerprint of every title/year/kind/status/stars/position/why/review was **identical before and after**. |
| AC3 README's own CSV | Extracted from `README.md` by regex and imported: 5 recognised as already present, 2 new, **0 problems** — including the quoted field and the trailing-empty-`why` row. |
| AC4 loose input resolves | `title` alone is enough; candidates come back with posters. |
| **AC5 nothing guessed, nothing dropped** | 4 rows in → 4 rows out. `The Thing` (no year, no kind) → **6 candidates, needs a choice**. `Cowboy Bebop, 1998` (no kind) → the anime **and** the game both offered. `Zzzqqxnonexistent` → **unmatched, not dropped**. `Akira, 1988, anime` → matched. |
| AC6 preview writes nothing | Row count **11 → 11** across a preview of three new titles. Preview and commit are separate endpoints, so this is structural. |
| **AC7 atomic commit** | Sabotaged the **third** insert of four with a simulated disk failure. Two rows had already been written. Result: rows **11 → 11**, and the set of titles was byte-identical before and after. **The rollback removed them.** |
| AC8 ids skip the search | A row with `tmdb_id`/`igdb_id` resolves with no lookup — this is what makes AC2 exact. |
| AC9 duplicates | Reported as *"already on your list"*, never re-added and **never updated** — an import cannot quietly drag something out of the Seen archive. |
| AC10 gap-tolerant append | New rows land at `MAX+10`, preserving T-7's scheme. |
| AC11 stays local | Loopback only; `media-list-export*.csv` is gitignored (verified). |

Chatbot realism: a pasted **``` fence and a BOM are stripped** on parse, because the README
tells Evan to paste raw output and that is what raw output looks like.

Zero `pageerror`s and zero console errors.

## Note
The test imports left real titles on the list (Akira, Outer Wilds, Attack on Titan, The
Handmaiden was rolled back). They are plausible watchlist entries rather than junk, and are
Evan's to remove if he does not want them.
