# T-5 — The wall: build evidence

| AC | Result |
| --- | --- |
| AC1 drag | Pointer drag moved the deck **1 → 5 of 11** with momentum and a clean settle. Cards track the cursor with transitions disabled mid-drag (a transition there makes the gesture feel like wading). |
| AC2 buttons | One click: **1 → 2**. Three more clicks: **2 → 5**. Exactly one card each, no compounding. |
| AC3 keyboard | `←` **5 → 4**; `Home` **→ 1**. Enter opens the centre card. Focus ring is a token outline. |
| **AC4 drag ≠ click** | After a 360px drag the URL was still `#/` — **no navigation**. A clean click on the centre card went to `#/title/6`. Both behaviours in one run. |
| AC5 · 0 titles | Real empty state: *"Nothing on the list yet"* + an **Add something** button, and **zero** carousels in the DOM. |
| AC5 · 1 title | `1 of 1`, one card, and both side buttons leave it at `1 of 1` — no degenerate loop. |
| AC5 · 211 titles | **7 cards in the DOM at rest, 13 mid-throw — not 211.** Sustained **69 fps** through a hard throw. |
| AC6 reduced motion | Card `transitionDuration` collapses to `1e-06s` and stepping still works (`1 of 11` → `2 of 11`). Inherited from T-2's global token override — no media query was written here. |
| AC7 skin-driven | **Zero** colour literals in the coverflow CSS block; 12 `var(--…)` references. Rendered in `system`, `nocturne` and `paperback`. |
| AC8 caption | Centre card shows kind chip, title, year and the `why` in quotes, plus `n of N`. |

Zero `pageerror`s and zero console errors across every run.

## The defect this ticket found in itself

**Clicking the centre card did nothing.** `stage.setPointerCapture()` retargets every
subsequent pointer event to the capture element, so by `pointerup` `event.target` was the
stage, and `event.target.closest('.cf-card')` walks *upward* — from the stage it can never
find a card. The carousel dragged perfectly and simply refused to open anything.

It is the kind of bug that survives a casual look: no error, no warning, and the buttons and
keyboard both worked. **Fixed** by remembering the pressed card at `pointerdown`, where the
target is still correct. Re-verified: a click now lands on `#/title/2`.

## Notes

- The `#/title/{id}` route is registered here with a placeholder so the carousel has
  somewhere to open to; **T-6 fills it in.**
- The 211-title test used synthetic rows re-using already-cached artwork, so the images were
  real files rather than empty frames. All 200 were removed afterwards — the list is back to
  its 11 real titles, verified by query.
- Chromium only.
