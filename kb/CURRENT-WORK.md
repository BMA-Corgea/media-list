# CURRENT WORK — media-list

## Live scope amendment: VIDEO GAMES (Evan, 2026-09-04, mid-build)

Evan added video games to the list after the ticket set was filed. This is IN SCOPE and
must be carried into every affected ticket's `refine` stage — `respec` is direction-only,
so the four child tickets below were still at `intake` when the change landed and their
specs get written with games included rather than amended afterwards.

**`kind` is now one of: `anime` · `movie` · `live-action` · `game`.**

### The source decision: IGDB, not RAWG

IGDB serves **portrait box art** at roughly 2:3 — the same shape as a film poster — so games
sit on the same carousel as everything else. RAWG's primary image is a landscape screenshot,
which would have forced either letterboxed cards or a second card shape on the wall. The wall
is the product, so the card shape decided the API.

IGDB authenticates through Twitch (`IGDB_CLIENT_ID` + `IGDB_CLIENT_SECRET` → client_credentials
exchange at `id.twitch.tv/oauth2/token` → bearer valid ~60 days). Token caches under gitignored
`data/`, refreshes on 401. **Evan has not supplied these yet** — T-3 must degrade to screen-only
search when they are absent rather than failing.

### What each affected ticket owes

| Ticket | What games change |
| --- | --- |
| `T-3` | IGDB client alongside TMDB/AniList; merged search results; per-kind details; games have **no `imdb_id`** — schema must allow null without the title page losing its link row |
| `T-4` | Search spans screen titles and games in one result set; `kind` gains `game` |
| `T-6` | Outbound link is per kind — IMDb for screen, IGDB game page for games. **UI copy adapts**: a game is *played*, not *watched*, even though the stored status stays `seen` |
| `T-7` | Filter chips gain `game` |
| `T-10` | CSV `kind` column accepts `game`; game rows resolve against IGDB |

`README.md` and `.env.example` are already updated — the starter CSV, the chatbot prompt and
the credentials table all cover games as of this amendment.

## The board

`T-1` (direction) is complete and routed. Grant **`G-1`** delegates *all* gates on the T-1
branch to the agent — Evan: *"Just loop through it. Go ahead and build it. I don't need to
approve anything. Get through all the tickets"*. Future tickets filed under T-1 inherit it;
it lasts until T-1 reaches a terminal state; `tracker.mjs revoke G-1` ends it early.

Build order: **T-2** → T-3 → T-4 → {T-5, T-6, T-7, T-8} → T-9 (after T-6), T-10 (after T-7),
T-11 (after T-5).


## Obligation handed from T-3 to T-4 (2026-09-04)

**A stored TMDB title MUST persist its `media_type`.** TMDB's movie and tv ids are separate
namespaces — id `30991` is *Cowboy Bebop* as a tv id and *The Curse of the Living Corpse*
(1964) as a movie id — so `GET /api/details/tmdb/<id>` without a `media_type` cannot be
answered. T-3 makes it fail loudly with a 400 rather than guess, because guessing returned a
plausible wrong title with the wrong poster and the wrong IMDb id.

T-4 stores it in the `detail` JSON column. T-6 and T-10 need it too, for any refresh or
re-resolve.


## IGDB credentials — half supplied (2026-09-04)

Evan supplied one 30-character value: it is parked in gitignored `.env` as
`IGDB_PENDING_VALUE`. **IGDB needs two**: `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET`, both
30 characters, both from the same Twitch application at dev.twitch.tv/console.

Twitch returns the identical error (`400 invalid client`) whether the id or the secret is
wrong, so the supplied value cannot be identified on its own — tested both ways, both
inconclusive. Once the second value arrives, put them on the right lines and the whole IGDB
path (T-3 AC1/AC5/AC8, and games in T-4/T-7/T-10) re-runs.
