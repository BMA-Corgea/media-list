# T-4 — Build evidence

| AC | Result |
| --- | --- |
| AC1 one search, one click | Typed `perfect blue`, clicked the poster, got *"Added Perfect Blue. It is at the end of your queue."* Stored row carries title, year, kind, summary, local poster + backdrop, genres and a working IMDb link — **nothing typed but `why`**. |
| AC2 only `why` is typeable | DOM audit of the whole add flow found **two** inputs: `#q` (the search box) and `#why`. There is no field for summary, poster URL, link or genre anywhere. |
| AC3 `media_type` persisted | Stored rows carry `detail.media_type` (`tv` for Cowboy Bebop, `movie` for The Thing) — discharges T-3's recorded obligation. |
| AC4 duplicates | Re-adding Cowboy Bebop → **409** `{"detail": "Cowboy Bebop is already on your list", "existing_id": 1}`; table still held one row. Same message appears in the UI. |
| AC5 queue tail | Positions 10, 20, 30 — gap-tolerant, as T-7 requires. `status=queued`, `added_at` set. |
| **AC6 debounce** | Typed all 12 characters of `cowboy bebop` at 40ms intervals → **1 search request**. Measured by counting `/api/search` requests in the browser, not asserted. |
| AC7 artwork local | Query across every stored row for a `poster_path`/`backdrop_path` starting `http` → **none**. All `/art/…`. |
| AC8 list | All three titles rendered with local art and their `why` lines. |
| AC9 remove | Clicked remove → grid went **3 cards → 2**. |

## The screenshot worth keeping

`search-and-pick.png` is the product's whole argument in one frame: searching `cowboy bebop`
puts the **1998 anime**, the **2021 live-action** and the **2001 film** side by side with
three different posters and three different kind chips. That is the thing a spreadsheet row
cannot do.

## Defect found and fixed during this ticket

The brand became a `<button>` so it could navigate home, and kept its native border — it
rendered as a boxed button in the top-left. Fixed in `base.css` (border/background/padding
reset on `.brand`); re-verified `borderTopWidth: 0px` in the browser.

## Errors

Final run: **zero** `pageerror`s and zero console errors. An earlier run logged one console
line — `Failed to load resource: 409 (Conflict)` — which is the browser reporting the
duplicate-refusal HTTP status from the AC4 test, i.e. the feature working, not a fault.

## Gaps

- Games still cannot be added — IGDB credentials incomplete at the time of this run. The
  add path is source-agnostic and will carry games with no change; unproven until then.
- Chromium only.
