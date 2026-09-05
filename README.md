# media-list

An organizer for all the stuff I've been meaning to get to — anime, movies, live action and
video games — built to be more fun than the spreadsheet it replaces.

A rotating carousel of cover art on the home page. A real page per title with a summary,
hero art and an IMDb link. One queue you order yourself, a wheel you can spin when you
can't decide, and a five-star review that files a title into the Seen archive once you're
done with it.

Runs locally on `127.0.0.1:7799`. **The app is public; the list is not** — the database,
the artwork it caches and every CSV export stay out of this repository.

> **Status: not built yet.** The design is settled and the work is filed; the code is on
> its way. The CSV contract below is final, so you can start building your list now.

---

## Starting your list — the CSV format

The importer is a **resolver**, not a strict loader. You give it rough rows; it searches
each one against TMDB, shows you the matches with their posters, and lets you settle
anything ambiguous before a single row is committed. So the file you bring can be loose.

### The starter format

```csv
title,year,kind,why
Cowboy Bebop,1998,anime,Everyone says the jazz soundtrack alone is worth it
Perfect Blue,1997,anime,Satoshi Kon — supposedly the one Aronofsky lifted from
The Thing,1982,movie,Practical effects that still hold up
Andor,2022,live-action,The one Star Wars thing adults keep recommending
Hollow Knight,2017,game,"Apparently the best 15 dollars anyone has ever spent"
Disco Elysium,2019,game,A detective RPG where you can lose an argument with your own brain
Frieren: Beyond Journey's End,2023,anime,
```

**`title` is the only required column.** Everything else helps and nothing else is
mandatory.

| Column | Required | What it does |
| --- | --- | --- |
| `title` | **yes** | What you'd type into a search box. Doesn't need to be the exact official title — the resolver handles near-misses. |
| `year` | no, but | The single most valuable optional field. "Cowboy Bebop" matches the 1998 anime, the 2021 live-action remake *and* the 2001 film; the year settles it without you having to. |
| `kind` | no | One of `anime`, `movie`, `live-action`, `game`. Which shelf it lands on. Left blank, it's inferred from what the source returns and you can correct it. |
| `why` | no | One line on why you wanted to watch it — who recommended it, what hooked you. Free text. Genuinely hard to reconstruct six months later, and it's the nicest thing on the title page. |

Rules that matter:

- **Header row required**, exactly these names, lowercase.
- `game` rows resolve against IGDB rather than TMDB; everything else about them works the same.
- Wrap any field containing a comma in double quotes; double up internal quotes
  (`"Léon: The Professional"`, `"She said ""watch it twice"""`).
- UTF-8. Non-English titles and diacritics are fine — `Shin Sekai Yori`, `Amélie`,
  `僕のヒーローアカデミア` all resolve.
- Blank `why` fields are fine; leave the comma in place.
- Rows the resolver can't match aren't dropped silently — they come back on the review
  screen for you to search by hand or discard.
- Import order becomes your initial queue order. Reorder by dragging afterwards.

### A prompt worth pasting into a chatbot

If you don't have a list yet, this gets you one in the right shape:

> Give me a CSV of things I should watch or play, with the header row `title,year,kind,why`.
> `kind` must be exactly one of `anime`, `movie`, `live-action`, or `game`. `year` is the
> original release year. `why` is one short sentence on why it's worth my time. Quote any
> field containing a comma. Give me 50 rows, mixing all four kinds, and skew toward things
> that are well regarded rather than merely popular. Output only the CSV — no commentary,
> no code fence.

Then paste the result into the importer, check the matches, commit.

### The export format

Export is a full-fidelity backup, so it carries more than the starter format:

```csv
title,year,kind,why,status,stars,queue_position,tmdb_id,igdb_id,imdb_id,added_at,watched_at,review
```

Any export re-imports cleanly. The extra columns are optional on the way in, so a starter
CSV and a full export both go through the same door:

| Column | Notes |
| --- | --- |
| `status` | `queued` or `seen`. Defaults to `queued`. |
| `stars` | `1`–`5`, or blank if unrated. |
| `queue_position` | Integer. Blank rows are appended in file order. |
| `tmdb_id` / `igdb_id` | Whichever source the title came from. When present, the resolver trusts it and skips the search entirely — this is what makes an export round-trip exactly. A game has an `igdb_id` and no `tmdb_id`; a film is the other way round. |
| `imdb_id` | The outbound link for screen titles; sourced from TMDB, never typed by hand. Blank on games, which link to IGDB instead. |
| `added_at`, `watched_at` | ISO-8601 dates. |
| `review` | Free text, whatever you wrote after watching. |

---

## Where the data comes from

| Source | Used for | Key |
| --- | --- | --- |
| [TMDB](https://www.themoviedb.org/) | Posters, backdrops, summaries, genres, and the IMDb id behind every outbound link | `TMDB_API_KEY` |
| [AniList](https://anilist.co/) | Anime specifics TMDB is thin on — studio, season, episode count, romaji *and* English titles | none needed |
| [IGDB](https://www.igdb.com/) | Everything about games — portrait box art, summaries, genres, platforms, developer, release year | `IGDB_CLIENT_ID` + `IGDB_CLIENT_SECRET` |
| [Pexels](https://www.pexels.com/) | Ambient imagery only: shelf headers, empty states, the backdrop behind the carousel | `PEXELS_API_KEY` |

Pexels is deliberately **not** a source of title artwork — stock photography can't give you
real key art, and a poster wall made of stock photos is the spreadsheet problem wearing a
costume.

IMDb has no free public API. The IMDb links here come from TMDB's `imdb_id` field. Games have
no IMDb entry at all and link to their IGDB page instead.

IGDB was chosen over RAWG for one specific reason: IGDB serves **portrait box art** at roughly
the same 2:3 ratio as a film poster, so games sit on the same carousel as everything else
without breaking the card shape. RAWG's primary image is a landscape screenshot, which would
have meant either letterboxed cards or a second card shape.

This product uses the TMDB API but is not endorsed or certified by TMDB. Pexels imagery is
credited per-file in `credits.json` alongside the images.

---

## Running it

```bash
cp .env.example .env     # then fill in the API credentials it names
./start.sh
```

The SQLite database creates itself on first startup if it isn't there — there is no
migration step to remember and nothing to install a server for.

| | |
| --- | --- |
| Backend | FastAPI on `7799` (`MEDIA_LIST_PORT`) |
| Frontend | Vite, served by the backend in normal use; `5799` in dev |
| Database | SQLite at `data/media-list.db` (`MEDIA_LIST_DB`) |
| Host | `127.0.0.1` only, on purpose |

Loopback-only is a decision, not an oversight: this is a private list. If it ever needs to
reach a phone, it goes through the GUTS Bridge rather than binding wider.

---

## Testing

```bash
scripts/test.sh
```

One command, the whole suite: API tests (star validation, queue reorder arithmetic, CSV
export/import round-trip, import atomicity), the privacy boundary (`.gitignore` coverage
and the SPA traversal containment check), and the built-bundle content check. Cold-boot safe
— creates `.venv` and installs `requirements-dev.txt` if they're missing — and exits
non-zero on any failure. No port is bound; the API is driven in-process, so it never
collides with a server already running on `7799`.

The suite runs against a throwaway database (never `data/media-list.db`) and stubs every
metadata source by default, so it needs no `.env` and never reaches the network. A separate,
**opt-in** set of tests hits the real TMDB/AniList/IGDB APIs with real credentials; they are
skipped unless you ask for them:

```bash
scripts/test.sh --live      # requires a real .env
```

Any other argument is forwarded straight to `pytest` — `scripts/test.sh -k queue_order`,
`scripts/test.sh -x`, and so on.

---

## Skins

The look is swappable. A skin is **one CSS file** at `frontend/src/skins/<name>.css` whose
rules live entirely under `:root[data-theme="<name>"]`, plus **one row** in the skin
registry. Nothing else changes — the option appears in the switcher, applies before first
paint, and persists.

`base.css` is the only special one: it owns the bare `:root` and carries both the design
tokens and the component layer. That's why an alternate skin can be seventy lines of token
overrides and still restyle the entire app, including components written after it.

The contract is lifted from [repo-tour](https://github.com/BMA-Corgea/repo-tour), which in
turn took it from GLP Strong. It survives being moved, which is the point.

---

## What's not in here

The database, cached title artwork and CSV exports are gitignored — they'd reveal the very
thing this repo is meant to keep private. `.env` holds the API keys and is gitignored;
`.env.example` documents the names.

---

## License

MIT. See [LICENSE](LICENSE).
