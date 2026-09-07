-- media-list schema.
--
-- Applied in full on every boot, and every statement is IF NOT EXISTS. That guards the
-- STATEMENT, not what changed inside it: `CREATE TABLE IF NOT EXISTS titles (...)` is a
-- total no-op the moment a database already has `titles`, no matter what the parenthesised
-- column list says. So a new COLUMN reaches a fresh database only — exactly like a changed
-- CONSTRAINT does, not differently. `CREATE TABLE IF NOT EXISTS` is a NO-OP on a database
-- that already has the table, so editing a CHECK constraint (or adding a column) here
-- changes NOTHING on an existing one — the old shape survives, silently, and only a fresh
-- `rm -rf data` would ever show the new one. SQLite cannot ALTER a CHECK, so widening
-- `source` and `kind` below needed a real table rebuild. It lives in
-- `db.py::_rebuild_titles`, which builds the new table FROM THIS FILE so the two can never
-- drift.
--
-- PROVEN, not assumed: a `pages INTEGER` column was added here, on a database already
-- migrated to T-16, with `SCHEMA_VERSION` left alone. Booting again gave
-- `'pages' in table -> False`, and an insert naming it failed with
-- `no such column: pages`. A plain column is not self-applying.
--
-- The ONE statement in this file that really is self-applying is a NEW
-- `CREATE INDEX IF NOT EXISTS`: unlike the table, the object that statement guards (the
-- index) genuinely is absent from an old database, so it actually runs. A new COLUMN and
-- any CONSTRAINT change are both never self-applying — either one needs `SCHEMA_VERSION`
-- in db.py bumped alongside the edit, so `_rebuild_titles` carries it across.
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
