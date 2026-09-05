# T-7 — The queue: build and review evidence

## The defect this ticket found, and why it mattered

The first implementation took **both** neighbours from the caller and placed the title at
their midpoint. With rows at positions 5 and 10 that midpoint is always **7** — so inserting
four different titles "between them" gave all four position 7:

```
  5  game   Super Mario 64
  7  movie  The Thing          <- all four share 7
  7  anime  Perfect Blue
  7  anime  Cowboy Bebop
  7  live   Andor
 10  game   NieR: Automata
```

Order among them then fell back silently to `added_at`, so a title dropped at the top landed
last. The renumber never fired, because 7 genuinely *does* fit between 5 and 10 — the guard
was asking the wrong question.

**Fix:** only ONE bound now comes from the caller (`after_id` *or* `before_id`); the other is
read from the database as the row that is genuinely adjacent right now. The guard also
rejects a target another row already occupies, not merely one that doesn't fit.

Re-running the identical sequence against the fix: each title landed **directly after** the
row named, positions stayed unique and ascending, and the renumber fired when the gap ran out
(`5/7/10` → `10/11/12/15/20/60…`).

## Acceptance criteria

| AC | Result |
| --- | --- |
| AC1 ordered list | 11 rows with rank, poster, title, kind chip, year, `why`. |
| AC2 drag persists | Order after a drag survived a reload, identical list. |
| AC3 carousel agrees | Queue's first row and the wall's first card both `NieR: Automata` — same sequence, no second source of truth. |
| AC4 filters | `all · anime · movie · live-action · game`; heading and counts follow the filter; pressed chip is marked. |
| **AC5 the hard one** | Dragged a game to the top **inside the games filter**, then cleared it: the games reordered as asked, and all **8 non-game titles kept their exact relative order**. |
| AC6 gap exhaustion | Forced by repeated inserts into one gap. Renumber fired, positions came out strictly ascending and unique, nothing lost. |
| AC7 keyboard | `Alt+↑` on row 3 moved *Hollow Knight* above *Super Mario 64*. |
| AC8 one / zero | 1 title: renders, and `Alt+↑` is a harmless no-op. Filtered to a kind it isn't: *"Nothing in game"*, no rows, no error. 0 titles: *"Nothing queued"* + CTA. |
| AC9 skin-driven | **Zero** colour literals in the queue CSS, 15 token references; rendered in `nocturne` and `paperback`. |

Zero `pageerror`s and zero console errors across every run.

## Why the API takes neighbour ids rather than an index

An index is meaningless in a filtered view — index 0 of "games" is not index 0 of the queue.
Sending the **ids the user can actually see** makes AC5 correct by construction rather than by
a correction pass: the server places the title beside exactly those rows, and every row the
filter was hiding is never touched. This was chosen at plan time, before the arithmetic bug
was found, and it is why that bug was a numeric error rather than a design one.

## Notes

- `#/list` (T-4's placeholder grid, described in its own spec as "a plain grid proving the add
  worked") is **replaced** by `#/queue`. `views/list.js` deleted.
- Bundle-grep check from T-6 applied: `drag to reorder` and `qrow__handle` both present in
  the built JS.
- Chromium only; drag proven with a synthetic mouse, not a finger.
