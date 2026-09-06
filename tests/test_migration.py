"""T-16 AC4/AC5 — the `titles` rebuild, against a database shaped like the owner's.

WHY THIS FILE EXISTS AT ALL. `bootstrap` applies schema.sql on every boot and every
statement in it is `IF NOT EXISTS`. On a database that already has the table, that CREATE is
a NO-OP — so the CHECK constraints in a live database are the ones from the boot that first
created the file, and editing them in schema.sql changes nothing at all. The owner's own
database was verified still carrying `CHECK (kind IN ('anime','movie','live-action','game'))`
long after the file said otherwise. SQLite cannot ALTER a CHECK, so books needed a real
table rebuild: create, copy, drop, rename.

WHAT IS UNDER TEST IS DESTRUCTIVE, so what it is pointed at matters. The subject here is
built from the FROZEN pre-T-16 schema below, populated with the awkward shapes the owner's
real database actually had — a `seen` row with stars AND a review, a row whose
`poster_path` is NULL, rows from two different sources, and an id gap with an AUTOINCREMENT
high-water mark ABOVE max(id) because a row was deleted. The owner's real file is never
touched by this suite, and `scripts/test.sh` fails the whole run if its mtime so much as
moves.

The rebuild was additionally rehearsed by hand against a byte copy of his actual database
before any of this was written — 15 rows in, 15 rows out, full-table diff empty. These
tests are what keep it true.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from backend import db as dbmod
from backend.db import SCHEMA_VERSION, STAGING_TABLE, bootstrap, migrate

#: schema.sql exactly as it stood at 154a54a, the commit before T-16. Frozen on purpose:
#: this is the shape every database created before this ticket really has, and reading it
#: from the live file would make the test migrate a table that needs no migrating.
V1_SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL CHECK (source IN ('tmdb', 'igdb')),
    source_id       TEXT    NOT NULL,
    imdb_id         TEXT,
    anilist_id      INTEGER,
    title           TEXT    NOT NULL,
    original_title  TEXT,
    year            INTEGER,
    kind            TEXT    NOT NULL CHECK (kind IN ('anime', 'movie', 'live-action', 'game')),
    summary         TEXT,
    poster_path     TEXT,
    backdrop_path   TEXT,
    genres          TEXT,
    detail          TEXT,
    why             TEXT,
    status          TEXT    NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'seen')),
    stars           INTEGER CHECK (stars IS NULL OR stars BETWEEN 1 AND 5),
    review          TEXT,
    queue_position  INTEGER,
    added_at        TEXT    NOT NULL,
    watched_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_titles_source ON titles (source, source_id);
CREATE INDEX IF NOT EXISTS idx_titles_status_position ON titles (status, queue_position);
CREATE INDEX IF NOT EXISTS idx_titles_kind           ON titles (kind);
CREATE INDEX IF NOT EXISTS idx_titles_watched_at     ON titles (watched_at);
PRAGMA user_version = 1;
"""

#: The awkward shapes, not a tidy sample. Every one of these is here because the owner's
#: real database had it and a migration that only handles neat rows is not proven.
V1_ROWS = [
    # (source, source_id, imdb_id, title, year, kind, poster_path, why,
    #  status, stars, review, queue_position, watched_at)
    ("tmdb", "1091", "tt0084787", "The Thing", 1982, "movie", "a1.jpg",
     "Practical effects that still hold up", "queued", None, None, 50, None),
    ("tmdb", "30991", "tt0213338", "Cowboy Bebop", 1998, "anime", "a2.jpg",
     "Everyone says the jazz soundtrack alone is worth it", "queued", None, None, 30, None),
    ("igdb", "1074", None, "Super Mario 64", 1996, "game", "a3.jpg",
     "Supposedly the one that made everyone cry", "queued", None, None, 10, None),
    # The `seen` row: stars AND a review AND a watched_at AND no queue_position.
    ("igdb", "11208", None, "NieR: Automata", 2017, "game", "a4.jpg",
     None, "seen", 4, "Better than I expected, and the ending earns it.", None,
     "2026-09-05T04:56:55+00:00"),
    # The NULL poster — added through the UI before any art was cached. NULL, never "".
    ("tmdb", "332437", None, "Dungeon Crawler Carl", 2025, "live-action", None,
     None, "queued", None, None, 160, None),
]


def build_v1_database(path) -> None:
    """A database exactly as a pre-T-16 boot would have left it, rows and all."""
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    for row in V1_ROWS:
        conn.execute(
            """INSERT INTO titles (source, source_id, imdb_id, title, year, kind,
                    poster_path, why, status, stars, review, queue_position, watched_at,
                    genres, detail, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*row, json.dumps(["Drama"]), json.dumps({"media_type": "movie"}),
             "2026-09-05T04:26:31+00:00"),
        )
    # A DELETED row, so ids carry a gap and sqlite_sequence sits ABOVE max(id). Without
    # this the high-water mark and max(id) coincide and a rebuild that silently reset the
    # sequence would still pass — the bug would be invisible.
    conn.execute(
        "INSERT INTO titles (source, source_id, title, kind, added_at) "
        "VALUES ('tmdb', '999999', 'Deleted Later', 'movie', '2026-09-05T04:26:31+00:00')"
    )
    conn.execute("DELETE FROM titles WHERE source_id = '999999'")
    conn.commit()
    conn.close()


def snapshot(path, columns=None) -> list[dict]:
    """Every row, every column, ordered — NULL preserved as None, never flattened to ""."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    names = columns or [r[1] for r in conn.execute("PRAGMA table_info(titles)")]
    named = ", ".join(f'"{c}"' for c in names)
    rows = [dict(r) for r in conn.execute(f"SELECT {named} FROM titles ORDER BY id")]
    conn.close()
    return rows


def table_sql(path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'titles'").fetchone()[0]
    conn.close()
    return sql


def scalar(path, sql):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    value = conn.execute(sql).fetchone()
    conn.close()
    return value[0] if value else None


@pytest.fixture
def v1_db(tmp_path):
    """A populated pre-T-16 database of its own, per test."""
    path = tmp_path / "media-list.db"
    build_v1_database(path)
    return path


# ── the fixture is genuinely OLD, or none of this proves anything ────────────────────────


def test_the_v1_fixture_really_rejects_a_book(v1_db):
    """Guard the guard. If this database would accept a book already, every test below
    would pass while proving nothing at all — the migration would be a no-op dressed as a
    success. Both constraints are checked because both had to change."""
    conn = sqlite3.connect(v1_db)
    with pytest.raises(sqlite3.IntegrityError, match="source"):
        conn.execute("INSERT INTO titles (source, source_id, title, kind, added_at) "
                     "VALUES ('openlibrary', 'OL1W', 'A Book', 'movie', 'now')")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="kind"):
        conn.execute("INSERT INTO titles (source, source_id, title, kind, added_at) "
                     "VALUES ('tmdb', '1', 'A Book', 'book', 'now')")
    conn.rollback()
    assert "isbn" not in table_sql(v1_db)
    assert scalar(v1_db, "PRAGMA user_version") == 1
    conn.close()


def test_the_v1_fixture_has_the_awkward_shapes_it_claims_to(v1_db):
    """The fixture's own contract: if these shapes drift out of it, the tests that depend
    on them go quietly green instead of failing."""
    rows = snapshot(v1_db)
    assert len(rows) == 5
    assert sum(1 for r in rows if r["status"] == "seen") == 1
    assert sum(1 for r in rows if r["poster_path"] is None) == 1
    assert len({r["source"] for r in rows}) == 2
    seen = next(r for r in rows if r["status"] == "seen")
    assert seen["stars"] == 4 and seen["review"] and seen["queue_position"] is None
    # The high-water mark is ABOVE max(id) because a row was deleted.
    assert scalar(v1_db, "SELECT seq FROM sqlite_sequence WHERE name='titles'") > \
        scalar(v1_db, "SELECT MAX(id) FROM titles")


# ── AC4: 5 rows in, 5 rows out, every existing column byte-identical ─────────────────────


def test_the_migration_changes_no_value_in_any_pre_existing_column(v1_db):
    """THE PASS CONDITION. The full-table diff over the columns that carried his data must
    be empty — the same check the hand rehearsal ran against a byte copy of his real
    database, where it covered 15 rows including a review and a NULL poster."""
    columns = [r[1] for r in sqlite3.connect(v1_db).execute("PRAGMA table_info(titles)")]
    before = snapshot(v1_db, columns)

    bootstrap(v1_db)

    after = snapshot(v1_db, columns)
    assert after == before, "the rebuild altered a value it was only supposed to carry across"


def test_the_migration_keeps_every_row(v1_db):
    before = len(snapshot(v1_db))
    bootstrap(v1_db)
    assert len(snapshot(v1_db)) == before == 5


def test_the_seen_row_keeps_its_stars_and_its_review(v1_db):
    """The row that would hurt most to lose: it holds something he wrote."""
    bootstrap(v1_db)
    seen = [r for r in snapshot(v1_db) if r["status"] == "seen"]
    assert len(seen) == 1
    assert seen[0]["title"] == "NieR: Automata"
    assert seen[0]["stars"] == 4
    assert seen[0]["review"] == "Better than I expected, and the ending earns it."
    assert seen[0]["watched_at"] == "2026-09-05T04:56:55+00:00"
    assert seen[0]["queue_position"] is None


def test_a_null_poster_stays_null_and_does_not_become_an_empty_string(v1_db):
    """"Empty means NULL" is a project rule, and a rebuild is exactly where a value would
    get quietly coerced across."""
    bootstrap(v1_db)
    blank = [r for r in snapshot(v1_db) if r["title"] == "Dungeon Crawler Carl"]
    assert blank[0]["poster_path"] is None
    assert blank[0]["poster_path"] != ""


def test_queue_positions_survive_unchanged(v1_db):
    before = [r["queue_position"] for r in snapshot(v1_db)]
    bootstrap(v1_db)
    assert [r["queue_position"] for r in snapshot(v1_db)] == before


def test_the_autoincrement_high_water_mark_is_carried_across(v1_db):
    """Otherwise the next title added reuses the id of one he deleted, and a bookmark or an
    open tab silently points at a different title."""
    before = scalar(v1_db, "SELECT seq FROM sqlite_sequence WHERE name='titles'")
    bootstrap(v1_db)
    assert scalar(v1_db, "SELECT seq FROM sqlite_sequence WHERE name='titles'") == before


def test_the_new_constraints_are_actually_in_place_afterwards(v1_db):
    bootstrap(v1_db)
    sql = table_sql(v1_db)
    assert "'openlibrary'" in sql and "'book'" in sql and "isbn" in sql
    assert scalar(v1_db, "PRAGMA user_version") == SCHEMA_VERSION


def test_a_book_can_be_stored_after_the_migration(v1_db):
    """The whole point of the rebuild, stated as the thing the owner wanted."""
    bootstrap(v1_db)
    conn = sqlite3.connect(v1_db)
    conn.execute(
        "INSERT INTO titles (source, source_id, title, kind, isbn, added_at) "
        "VALUES ('openlibrary', 'OL59863W', 'The Dispossessed', 'book', '9780061054884', 'now')"
    )
    conn.commit()
    stored = conn.execute(
        "SELECT source, kind, isbn FROM titles WHERE source_id = 'OL59863W'").fetchone()
    conn.close()
    assert stored == ("openlibrary", "book", "9780061054884")


def test_isbn_is_null_on_every_migrated_row_rather_than_invented(v1_db):
    bootstrap(v1_db)
    assert all(r["isbn"] is None for r in snapshot(v1_db))


def test_every_index_survives_the_rebuild(v1_db):
    """`DROP TABLE` takes its indexes with it. The UNIQUE one is what makes "already on
    your list" detectable, so losing it would not raise — it would let duplicates in."""
    before = sorted(r[0] for r in sqlite3.connect(v1_db).execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"))
    bootstrap(v1_db)
    after = sorted(r[0] for r in sqlite3.connect(v1_db).execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"))
    assert after == before
    assert "idx_titles_source" in after

    conn = sqlite3.connect(v1_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO titles (source, source_id, title, kind, added_at) "
                     "VALUES ('tmdb', '1091', 'The Thing again', 'movie', 'now')")
    conn.close()


def test_integrity_check_still_passes(v1_db):
    bootstrap(v1_db)
    assert scalar(v1_db, "PRAGMA integrity_check") == "ok"


def test_no_staging_table_is_left_behind(v1_db):
    bootstrap(v1_db)
    assert scalar(v1_db, f"SELECT COUNT(*) FROM sqlite_master WHERE name='{STAGING_TABLE}'") == 0


# ── AC5, first half: running it again is a no-op ─────────────────────────────────────────


def test_a_second_boot_does_not_rebuild_again(v1_db):
    """`migrate` must RECOGNISE an already-migrated table, not rebuild it every boot.

    A rebuild that ran on every start would still be "correct" and would still pass every
    test above — while rewriting his entire list on every launch forever, and widening the
    crash window from once to always."""
    bootstrap(v1_db)
    conn = dbmod._connect(v1_db)
    try:
        assert migrate(conn) == "current"
    finally:
        conn.close()


def test_three_boots_leave_the_data_and_the_schema_identical(v1_db):
    bootstrap(v1_db)
    once, once_sql = snapshot(v1_db), table_sql(v1_db)
    bootstrap(v1_db)
    bootstrap(v1_db)
    assert snapshot(v1_db) == once
    assert table_sql(v1_db) == once_sql
    assert scalar(v1_db, "SELECT seq FROM sqlite_sequence WHERE name='titles'") is not None


def test_a_fresh_database_needs_no_migration_and_still_gets_the_new_shape(tmp_path):
    """The `rm -rf data` path: schema.sql alone, no rebuild, already correct."""
    fresh = tmp_path / "fresh.db"
    conn = dbmod._connect(fresh)
    try:
        assert migrate(conn) == "fresh"
    finally:
        conn.close()
    bootstrap(fresh)
    assert "'book'" in table_sql(fresh)
    assert scalar(fresh, "PRAGMA user_version") == SCHEMA_VERSION
    assert scalar(fresh, "SELECT COUNT(*) FROM titles") == 0


# ── AC5, second half: interrupt safety, PROVEN in a real process ─────────────────────────
#
# These spawn a real interpreter and kill it with `os._exit` part-way through the rebuild.
# `os._exit` skips finally-blocks, connection close and interpreter shutdown — the same
# thing a SIGKILL or a power cut does. Simulating the crash in-process by raising an
# exception would test the `except: ROLLBACK` path, which is a different and much weaker
# claim: it proves the code cleans up when it is still running.
#
# This project has learned four times that a guard nobody has watched fail is not a guard.

CRASH_SCRIPT = textwrap.dedent("""
    import os, sys
    db_path, trigger = sys.argv[1], sys.argv[2]
    os.environ["MEDIA_LIST_DB"] = db_path
    from backend import db as dbmod
    original = dbmod._connect
    def traced(path):
        conn = original(path)
        def trace(statement):
            if trigger in " ".join(statement.split()):
                os._exit(9)
        conn.set_trace_callback(trace)
        return conn
    dbmod._connect = traced
    dbmod.bootstrap(db_path)
    sys.exit(0)
""")


def _boot_and_die(repo_root, db_path, trigger) -> int:
    result = subprocess.run(
        [sys.executable, "-c", CRASH_SCRIPT, str(db_path), trigger],
        cwd=str(repo_root), capture_output=True, text=True, timeout=120,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(repo_root)},
    )
    return result.returncode


#: Where to die. Each is a genuinely different moment in the rebuild, named by the statement
#: the process is about to run when it is killed.
INTERRUPT_POINTS = [
    # Right after the copy INSERT: the staging table is full, `titles` still exists.
    ('SELECT COUNT(*) FROM "_titles_rebuild_staging"', "just after the rows were copied"),
    # THE DANGEROUS ONE: `DROP TABLE titles` has run. The original is gone and the only
    # copy of his list is in an uncommitted staging table.
    ('ALTER TABLE "_titles_rebuild_staging" RENAME TO "titles"', "just after DROP TABLE titles"),
    # Everything is done and the COMMIT has not happened yet.
    ("PRAGMA foreign_key_check", "on the last statement before COMMIT"),
]


@pytest.mark.parametrize("trigger,when", INTERRUPT_POINTS, ids=lambda v: v if " " in str(v) else "")
def test_a_process_killed_mid_rebuild_leaves_a_working_database(repo_root, v1_db, trigger, when):
    before = snapshot(v1_db)

    assert _boot_and_die(repo_root, v1_db, trigger) == 9, (
        f"the child was meant to be killed {when} but exited normally — the trigger "
        f"{trigger!r} no longer matches any statement in the rebuild, so this test has "
        "stopped interrupting anything"
    )

    # It opens, it is sound, and it still holds his list — the pre-migration one, whole.
    assert scalar(v1_db, "PRAGMA integrity_check") == "ok"
    assert snapshot(v1_db) == before
    assert scalar(v1_db, "PRAGMA user_version") == 1, "a half-applied migration claimed to be done"
    assert scalar(v1_db, f"SELECT COUNT(*) FROM sqlite_master WHERE name='{STAGING_TABLE}'") == 0


@pytest.mark.parametrize("trigger,when", INTERRUPT_POINTS, ids=lambda v: v if " " in str(v) else "")
def test_the_boot_after_a_kill_completes_the_migration_cleanly(repo_root, v1_db, trigger, when):
    before = snapshot(v1_db)
    _boot_and_die(repo_root, v1_db, trigger)

    bootstrap(v1_db)

    columns = list(before[0])
    assert snapshot(v1_db, columns) == before, f"data changed after a kill {when}"
    assert "'book'" in table_sql(v1_db)
    assert scalar(v1_db, "PRAGMA user_version") == SCHEMA_VERSION


def test_two_kills_in_a_row_still_leave_a_migratable_database(repo_root, v1_db):
    """The crash that happens again during the recovery boot."""
    before = snapshot(v1_db)
    _boot_and_die(repo_root, v1_db, 'ALTER TABLE "_titles_rebuild_staging" RENAME TO "titles"')
    _boot_and_die(repo_root, v1_db, 'SELECT COUNT(*) FROM "_titles_rebuild_staging"')
    assert snapshot(v1_db) == before

    bootstrap(v1_db)
    assert snapshot(v1_db, list(before[0])) == before
    assert "'book'" in table_sql(v1_db)


# ── the debris guard: a state the transaction makes unreachable, handled anyway ──────────


def test_an_orphaned_staging_table_is_recovered_rather_than_ignored(v1_db):
    """The silent catastrophe this guard exists to prevent.

    If `titles` is missing and the rows are sitting in the staging table, `bootstrap`
    without this guard creates a NEW EMPTY `titles` from schema.sql, reports nothing wrong,
    and the app opens on an empty list while every row still exists one table away. That is
    the worst possible failure: total apparent data loss, no error, and a database that
    looks fine."""
    conn = sqlite3.connect(v1_db)
    conn.execute(f'ALTER TABLE titles RENAME TO "{STAGING_TABLE}"')
    conn.commit()
    conn.close()

    bootstrap(v1_db)

    assert len(snapshot(v1_db)) == 5
    assert scalar(v1_db, f"SELECT COUNT(*) FROM sqlite_master WHERE name='{STAGING_TABLE}'") == 0
    assert "'book'" in table_sql(v1_db), "recovery happened but the migration then didn't"


def test_without_the_guard_that_same_database_opens_empty(v1_db, monkeypatch):
    """Proof the test above can fail — the guard removed, the loss appears.

    A recovery path nobody has watched fail is not a recovery path. With
    `_recover_staging` neutered, `bootstrap` is perfectly happy and the list is gone."""
    conn = sqlite3.connect(v1_db)
    conn.execute(f'ALTER TABLE titles RENAME TO "{STAGING_TABLE}"')
    conn.commit()
    conn.close()

    monkeypatch.setattr(dbmod, "_recover_staging", lambda conn: None)
    bootstrap(v1_db)

    assert snapshot(v1_db) == [], "the guard was disabled but nothing was lost — has it moved?"
    assert scalar(v1_db, f'SELECT COUNT(*) FROM "{STAGING_TABLE}"') == 5


def test_leftover_staging_beside_a_live_table_is_dropped_and_the_real_table_kept(v1_db):
    """The other debris shape. `titles` is authoritative here and it is not a judgement
    call: the rebuild drops staging BEFORE it commits, so a committed database holding both
    can only be one whose `titles` was never dropped."""
    conn = sqlite3.connect(v1_db)
    conn.execute(f'CREATE TABLE "{STAGING_TABLE}" (id INTEGER)')
    conn.execute(f'INSERT INTO "{STAGING_TABLE}" VALUES (1)')
    conn.commit()
    conn.close()

    bootstrap(v1_db)

    assert len(snapshot(v1_db)) == 5
    assert scalar(v1_db, f"SELECT COUNT(*) FROM sqlite_master WHERE name='{STAGING_TABLE}'") == 0


# ── the refusals and the pragma ──────────────────────────────────────────────────────────


def test_the_rebuild_refuses_to_run_if_the_new_schema_would_drop_a_column(v1_db):
    """Silently discarding a column of his data is not a migration. A schema that no longer
    declares `review` must stop the boot, not quietly take the reviews with it."""
    trimmed = V1_SCHEMA.replace("    review          TEXT,\n", "")
    conn = dbmod._connect(v1_db)
    try:
        with pytest.raises(RuntimeError, match="review"):
            migrate(conn, trimmed)
    finally:
        conn.close()

    # And it refused BEFORE touching anything.
    assert len(snapshot(v1_db)) == 5
    assert scalar(v1_db, "PRAGMA user_version") == 1


def test_foreign_keys_are_off_during_the_rebuild_and_on_again_afterwards(v1_db):
    """SQLite's rebuild procedure requires them off; `_connect` turns them on for every
    connection; and the pragma is a SILENT no-op inside a transaction. All three facts
    together are why this is worth a test rather than a comment."""
    seen = []
    original = dbmod._rebuild_titles

    def watched(conn, schema_text):
        seen.append(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        result = original(conn, schema_text)
        seen.append(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        return result

    dbmod._rebuild_titles = watched
    try:
        bootstrap(v1_db)
    finally:
        dbmod._rebuild_titles = original

    assert seen == [1, 1], "expected foreign_keys ON before and restored ON after"
    conn = dbmod._connect(v1_db)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_migrate_refuses_a_connection_that_already_has_a_transaction_open(v1_db):
    """`BEGIN IMMEDIATE` and the pragmas around it only mean what they say in autocommit."""
    conn = dbmod._connect(v1_db)
    try:
        conn.execute("INSERT INTO titles (source, source_id, title, kind, added_at) "
                     "VALUES ('tmdb', '5', 'x', 'movie', 'now')")
        assert conn.in_transaction
        with pytest.raises(RuntimeError, match="no transaction"):
            migrate(conn)
    finally:
        conn.rollback()
        conn.close()


# ── the schema reader, which is what keeps db.py and schema.sql from drifting ────────────


def test_the_staging_table_is_built_from_schema_sql_itself(repo_root):
    """`_split_schema` renames the real CREATE TABLE rather than duplicating it in Python.

    A hand-copied DDL in db.py would be a SECOND declaration of the same table, free to
    drift from the first — which is the exact class of bug this whole ticket is about."""
    schema_text = (repo_root / "backend" / "schema.sql").read_text(encoding="utf-8")
    create, others = dbmod._split_schema(schema_text, STAGING_TABLE)

    bare = dbmod._strip_comments(create)
    assert f'"{STAGING_TABLE}"' in bare
    assert "IF NOT EXISTS" not in bare.split("(")[0].upper(), (
        "staging must not silently reuse an existing table"
    )
    # The constraints came from the file, not from a copy of them.
    assert "'openlibrary'" in bare and "'book'" in bare and "isbn" in bare
    assert any("idx_titles_source" in o for o in others)
    assert any("user_version" in o for o in others)


def test_the_schema_file_and_db_py_agree_on_the_version(repo_root):
    """Two numbers that must move together, and nothing else enforces it."""
    schema_text = (repo_root / "backend" / "schema.sql").read_text(encoding="utf-8")
    import re
    stamped = re.search(r"PRAGMA\s+user_version\s*=\s*(\d+)", schema_text)
    assert stamped, "schema.sql no longer stamps user_version"
    assert int(stamped.group(1)) == SCHEMA_VERSION, (
        f"schema.sql stamps {stamped.group(1)} but db.py::SCHEMA_VERSION is {SCHEMA_VERSION}. "
        "A constraint change with only one of these bumped either migrates forever or never."
    )
