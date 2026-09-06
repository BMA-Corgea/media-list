-- media-list schema.
--
-- Applied in full on every boot. Every statement is IF NOT EXISTS, which made this file
-- the whole migration story for as long as changes were additive.
--
-- T-16 IS THE TICKET THAT BROKE THAT, and the comment below used to promise otherwise.
-- `CREATE TABLE IF NOT EXISTS` is a NO-OP on a database that already has the table, so
-- editing a CHECK constraint here changes NOTHING on an existing database — the old
-- constraint survives, silently, and only a fresh `rm -rf data` would ever show the new
-- one. SQLite cannot ALTER a CHECK, so widening `source` and `kind` below needed a real
-- table rebuild. It lives in `db.py::_rebuild_titles`, which builds the new table FROM
-- THIS FILE so the two can never drift.
--
-- So: adding a COLUMN or an INDEX here is still self-applying. Changing a CONSTRAINT is
-- not, and needs `SCHEMA_VERSION` in db.py bumped alongside the edit.
-- `user_version` is what the migration branches on — it is stamped at the bottom.

CREATE TABLE IF NOT EXISTS titles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Where this record came from. 'tmdb' for film/tv/anime, 'igdb' for games,
    -- 'openlibrary' for books. The pair is the identity: the same numeric id means
    -- different things per source.
    -- 'anilist' is deliberately absent: it DECORATES an existing record and never
    -- replaces one (see sources/anilist.py), so it is never a row's origin.
    source          TEXT    NOT NULL CHECK (source IN ('tmdb', 'igdb', 'openlibrary')),
    source_id       TEXT    NOT NULL,

    -- Games have no IMDb entry at all, so this is nullable by design, not by accident.
    imdb_id         TEXT,
    anilist_id      INTEGER,
    -- Books have no IMDb id and films have no ISBN, so this is nullable for the same
    -- reason imdb_id is. Part of the published CSV contract (README.md) as of T-16.
    isbn            TEXT,

    title           TEXT    NOT NULL,
    original_title  TEXT,
    year            INTEGER,
    kind            TEXT    NOT NULL CHECK (kind IN ('anime', 'movie', 'live-action', 'game', 'book')),

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

-- Bumped to 2 by T-16. `db.py::SCHEMA_VERSION` must match: it is the flag that tells an
-- existing database its `titles` table predates the rebuild and has to be rebuilt.
PRAGMA user_version = 2;
