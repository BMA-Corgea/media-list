# T-6 — Title page: build and review evidence

## Acceptance criteria

| AC | Result |
| --- | --- |
| AC1 reads as a page | Backdrop hero with scrim + poster + kind chip + title + year, then summary, facts, `why`, actions. Screenshots attached. |
| AC2 anime alt titles | *Cowboy Bebop* shows `カウボーイビバップ` beneath the title. AniList returned romaji **and** English both equal to "Cowboy Bebop", and **neither was rendered** — the dedupe set drops any alternate equal to a name already shown. |
| AC3 per-kind facts | **Anime:** Studio *Sunrise* · Season *Spring 1998* · Episodes *26* · Status *Ended* · Genres. **Game:** Developer *Team Cherry* · Platforms (10) · Genres. **Series:** Episodes *62* · Status *Ended* · Genres. **Zero empty labels on every page tested.** |
| AC4 per-kind link | Game → `View on IGDB` → `igdb.com/games/hollow-knight`. Screen → `View on IMDb` → `imdb.com/title/tt0903747/`. Sparse title with neither → **no link element at all** (`link: null`), not a dead link. |
| AC5 copy adapts | Game: **"Mark as played"**. Anime, film and series: **"Mark as watched"**. Stored status is untouched — only the label differs. |
| AC6 `why` editable | *The Truman Show* had none → edited in place → `"A friend said it hits differently after thirty"` → **survived a reload**. Clearing it with whitespace stored SQLite `null` (`typeof → 'null'`), not `""`. |
| AC7 move to top | Wall's first card went **The Thing → NieR: Automata**. Written as `MIN(queue_position) − 10`, so no other row was renumbered. |
| AC8 remove | Returned to `#/`, and `GET /api/titles/13` afterwards → **404**. |
| AC9 missing id | `#/title/999999` → *"No such title"* with a **Back to the wall** button. |
| AC10 sparse data | A row with no backdrop, summary, genres, `why`, year or link renders a complete page: no hero art class, no summary block, no facts list, no link — body height 166px, **no holes, no empty labels**. |

## Review finding: the build passed with an undefined identifier

`main.js` referenced `titleView` while its `import` was missing — an earlier edit script threw
before writing that line. **`npm run build` reported success anyway** (`✓ built in 294ms`), and
the app would have died at runtime with `titleView is not defined`.

Caught not by the build but by noticing the bundle had gone *down* 13.68 kB → 13.62 kB after
supposedly adding two modules, then grepping the output for strings only the new view
contains. Both were absent. After the real import: 18.68 kB, both strings present.

**The lesson, recorded because it will recur:** a green Vite build is not evidence that a
module is wired in. The cheap check is to grep the bundle for a string unique to the new
code. Done here for every subsequent build in this ticket.

## Notes and gaps

- **"Mark as played/watched" is present but disabled**, with a tooltip saying rating arrives
  with T-9. The affordance is deliberately visible so the page is not silently missing its
  most important action; T-9 wires it.
- The kind→verb mapping lives in one file (`frontend/src/kinds.js`) so T-9 reuses it rather
  than re-deciding that games are played.
- Chromium only.
