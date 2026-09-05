# T-3 — Build, review and verify evidence

## Acceptance criteria

| AC | Result |
| --- | --- |
| AC1 merged search | `/api/search` returns TMDB results with a per-source status block and a `disabled` list. IGDB half **unproven — no credentials yet** (see gaps). |
| AC2 kind inference | Proven against named titles: `Frieren`→anime · `Perfect Blue`→anime · `Cowboy Bebop` (1998)→anime · `Andor`→live-action · `Breaking Bad`→live-action · `The Thing`→movie · **`Toy Story`→movie**. That last one is the test that matters: genre 16 alone would have filed it as anime, and the ANDed Japanese check is what stops it. |
| **AC3 headline** | `cowboy bebop` → **1998 anime `tmdb:30991`**, **2021 live-action `tmdb:84469`**, **2001 film `tmdb:11299`** — three kinds, three ids, three posters, all in one result set. |
| AC4 details enrich | `tmdb/30991?media_type=tv` → `imdb_id tt0213338`, `anilist_id 1`, `studio Sunrise`, `season Spring 1998`, `episodes 26`, romaji + English titles. `tmdb/1091` (*The Thing*) → `tt0084787`, `runtime 109`, **no AniList decoration** — enrichment fires only for anime. |
| AC5 games have no IMDb | Code path returns `imdb_id: null` and an `igdb_url`; schema accepts it (proven in T-2). **Live call unproven — no credentials.** |
| AC6 artwork cached | 4 files in `data/art/`, content-addressed; a second identical request produced **no new files and byte-identical contents**; `/art/907f14…jpg` serves 200 `image/jpeg` 85834 bytes; stored fields are `/art/…` paths, never remote URLs. |
| AC7 degrade | Bad TMDB key → `sources.tmdb.ok=false` with a reason, app still up. **No** sources configured → `503` with an actionable message and `/api/health` still 200. Throughout this ticket IGDB was genuinely absent and search worked anyway, reporting `disabled: ["igdb"]`. |
| AC8 token cached | 5 sequential `token()` calls → **1 Twitch exchange**, one distinct token; cache file `0600`; expiry ~60 days; `force=True` re-exchanges; an expired cache re-exchanges on its own. Proven with a stubbed transport, since there are no credentials. |
| AC9 honest failure | A deliberately corrupted key returned `{"tmdb": {"ok": false, "error": "credentials rejected — check the key in .env"}}` — **not** a silent empty list. |

## Review findings — both in this ticket's own code, both fixed

### 1. `tmdb.details()` guessed the namespace and returned the wrong title

TMDB's movie and tv ids are **separate namespaces**. The first implementation tried `movie`
then `tv` when the caller gave no hint. That does not fail — it succeeds with a different,
entirely plausible title:

```
/api/details/tmdb/30991            -> "The Curse of the Living Corpse" (1964)
/api/details/tmdb/30991?media_type=tv -> "Cowboy Bebop" (1998)
/api/details/tmdb/550              -> "Fight Club"
/api/details/tmdb/550?media_type=tv   -> "Till Death Us Do Part"
```

Wrong title, wrong poster, wrong IMDb id — and T-4 would have stored it. **Fixed:** the
function now refuses without a `media_type` rather than guessing. Search results already
carry it. The obligation this creates for T-4 (persist `media_type` with any stored TMDB
title) is recorded in `kb/CURRENT-WORK.md` so it cannot be lost between tickets.

### 2. A caller's mistake was reported as `502 Bad Gateway`

Every `SourceError` was wrapped as 502, so "you forgot media_type" looked like an upstream
outage. **Fixed:** 400 and 404 pass through; 401/429/5xx still become 502, which is correct
from the caller's side. Now: missing `media_type` → **400**, nonexistent id → **404**,
unknown source → **404**, good request → **200**.

## Regression inherited from T-2

This ticket added routes, so T-2's traversal check was re-run as required:
`../../.env` and `../../.git/config` both return the SPA shell with **0 secrets in the body**.

## Honest gaps

- **The entire IGDB live path is untested.** No credentials exist yet. What *is* proven:
  availability gating, the token cache logic end to end against a stub, a named actionable
  error when credentials are absent, and search degrading to TMDB-only. What is **not**:
  a real apicalypse query, real cover art, real ranking. This is stated rather than implied,
  and it re-runs the moment Evan supplies the Twitch client id and secret.
- **AniList matching is fuzzy by nature** — there is no TMDB→AniList id mapping. It is
  constrained to decorate only (it may add studio/episodes/season/titles; it may never change
  `title`, `year` or `kind`), so a wrong match degrades a detail rather than corrupting a
  record. Not the same as being right every time.
- Search deliberately does **not** download artwork — caching every candidate's poster on
  every keystroke would pull megabytes per character. Caching happens at `/api/details`,
  which is the call that precedes storing. Recorded in the plan before it was built.
