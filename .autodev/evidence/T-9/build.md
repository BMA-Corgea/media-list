# T-9 — Review and the Seen archive: build evidence

| AC | Result |
| --- | --- |
| AC1 rating from the title page | T-6's disabled button is live. Clicking it asks *"How was it? (required)"* and picking a star **is** the action — no separate confirm, so there is no half-finished state to leave behind. After: 5 filled stars, a date line, a review box. |
| AC2 the verb is right | The game's button read **"Mark as played"** and its line **"played 9/4/2026"** — read from `kinds.js`, T-6's single source. |
| **AC3 leaves the queue, not deleted** | Verified on **all three** surfaces, not one: absent from the queue (9 rows), absent from the wheel (9 wedges), and `status=seen`, `queue_position=NULL`, `watched_at` stamped — while **total rows stayed 11**. |
| AC4 the archive | `Seen — 2`, each card with art, stars, date and review. Sorting by rating gave `[5, 4]`. Filtering to `game` gave *"Seen — 2 game"*. |
| **AC5 un-watching keeps the opinion** | API and UI both: `status → queued`, back at the **end** (position 120, the max), `watched_at` cleared, and **stars 5 and the review both intact**. |
| AC6 stars validated | `0`, `6`, `"three"`, `3.5` and `true` all → **400**. `status: seen` with no stars → **400** (a rating is required to be finished with something). `4` → 200. `true` matters: in Python `isinstance(True, int)` is True, so booleans are rejected explicitly. |
| AC7 review editable | Written, saved, **survived a reload** verbatim. |
| AC8 empty archive | *"Nothing here yet — Finish something and rate it, and it lands here for good."* with a way back to the wall. |
| AC9 skin-driven | No colour literals; stars use `--star`, the rating block uses `--seen`. |

Zero `pageerror`s and zero console errors.

## Details worth recording

- **"Move to top of queue" is hidden on a seen title** and shown on a queued one — verified by
  reading both pages' action rows. A queue action on something out of the queue is nonsense.
- **The seen listing is ordered by `watched_at DESC`, not `queue_position`.** Seen rows have
  no position at all, so the queue's ordering clause would have been meaningless for them —
  found while locating, fixed before it could be a bug.
- **Un-watch appends at MAX+10 rather than restoring the old position.** The queue moved on
  while the title was away; a resurrected stale position would be wrong. Stars and review are
  deliberately *not* cleared, so a rewatch keeps the first opinion.

## Gaps
Chromium only. No automated runner.
