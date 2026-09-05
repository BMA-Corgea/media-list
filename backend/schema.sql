-- media-list schema.
--
-- Applied in full on every boot. Every statement is IF NOT EXISTS, so this file IS the
-- migration story: there is no framework, no version table to hand-edit, and no step to
-- remember. `user_version` is stamped so a future ticket can branch on it if it ever needs
-- to alter a column rather than add one.

CREATE TABLE IF NOT EXISTS titles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Where this record came from. 'tmdb' for film/tv/anime, 'igdb' for games.
    -- The pair is the identity: the same numeric id means different things per source.
    source          TEXT    NOT NULL CHECK (source IN ('tmdb', 'igdb')),
    source_id       TEXT    NOT NULL,

    -- Games have no IMDb entry at all, so this is nullable by design, not by accident.
    imdb_id         TEXT,
    anilist_id      INTEGER,

    title           TEXT    NOT NULL,
    original_title  TEXT,
    year            INTEGER,
    kind            TEXT    NOT NULL CHECK (kind IN ('anime', 'movie', 'live-action', 'game')),

    summary         TEXT,
    -- Filenames inside the gitignored art cache, never remote URLs: the wall must render
    -- with the network off, and a cached poster reveals the list.
    poster_path     TEXT,
    backdrop_path   TEXT,
    genres          TEXT,            -- JSON array
    detail          TEXT,            -- JSON object: per-kind extras (platforms, studio, episodes…)

    -- Why the owner wanted it. Free text, his words.
    why             TEXT,

    status          TEXT    NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'seen')),
    stars           INTEGER CHECK (stars IS NULL OR stars BETWEEN 1 AND 5),
    review          TEXT,

    -- Gaps are allowed and expected: reordering rewrites positions rather than shuffling
    -- neighbours, so 10, 20, 30 is a normal state.
    queue_position  INTEGER,

    added_at        TEXT    NOT NULL,
    watched_at      TEXT
);

-- One row per thing, per source. This is what makes "already on your list" detectable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_titles_source ON titles (source, source_id);

CREATE INDEX IF NOT EXISTS idx_titles_status_position ON titles (status, queue_position);
CREATE INDEX IF NOT EXISTS idx_titles_kind           ON titles (kind);
CREATE INDEX IF NOT EXISTS idx_titles_watched_at     ON titles (watched_at);

PRAGMA user_version = 1;
