"""SQLite access and the self-creating database.

The whole bootstrap story is here. There is no migration command to run and no server to
install: opening the app is what builds the database. Deleting `data/` and restarting is a
supported action, and it is how this ticket is tested.

T-16 added the second half of that story. `schema.sql` alone stopped being enough the moment
a CHECK constraint had to change — see `_rebuild_titles` below for what that costs and why
it is written the way it is.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import config

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

#: Must match `PRAGMA user_version` at the bottom of schema.sql.
#:
#: This is the flag, and the ONLY flag, that says whether an existing `titles` table predates
#: the T-16 rebuild. Bump BOTH numbers together whenever a CONSTRAINT changes OR a COLUMN is
#: added — neither one is self-applying. `CREATE TABLE IF NOT EXISTS` is gated on the TABLE
#: already existing, not on what changed inside its definition, so it is a total no-op on any
#: database that already has `titles` — proved live by adding a column here without bumping
#: this number and watching `no such column` on the next insert. The only statement in
#: schema.sql that really is self-applying is a NEW `CREATE INDEX IF NOT EXISTS`, because the
#: object it guards (the index) genuinely is absent from an old database.
SCHEMA_VERSION = 2

#: The half-built table `_rebuild_titles` fills before it swaps. Named, not anonymous, so
#: that debris from an impossible crash is recognisable rather than mysterious.
STAGING_TABLE = "_titles_rebuild_staging"

#: `(?!\w)` after the table name so `titles_archive` (or any future sibling table) can never
#: match — without it, "titles" is a valid PREFIX match too, since the optional closing quote
#: is, well, optional.
_CREATE_TITLES = re.compile(
    r"(CREATE\s+TABLE\s+)(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?titles[\"'`\]]?(?!\w)",
    re.IGNORECASE,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Rows reference nothing yet, but T-9 and T-10 will; turning this on now means the
    # constraint exists from the first row rather than being retrofitted over live data.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the carousel read while an import writes (T-10) without either blocking.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ── reading schema.sql as statements ─────────────────────────────────────────────────────
#
# The rebuild builds its new table FROM schema.sql rather than from a copy of the DDL kept
# here. That is the whole point: a hand-copied CREATE TABLE in this file would be a second
# declaration of the same table, free to drift from the first one, and "the schema file said
# one thing and the live database said another" is precisely the bug T-16 exists to fix.


def _blank(match: re.Match) -> str:
    """Every character but a newline turned to a space — same LENGTH as what it replaces."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_comments(sql: str) -> str:
    """`--` and `/* */` blanked out (not deleted — see `_blank`). Used to LOOK at a
    statement, never to execute one, and LENGTH-PRESERVING on purpose: `_split_schema`
    finds a match here and then slices the identical span out of the raw, un-stripped text,
    which only lines up if stripping never shifts anything."""
    sql = re.sub(r"/\*.*?\*/", _blank, sql, flags=re.S)
    return re.sub(r"--[^\n]*", _blank, sql)


def _statements(script: str) -> list[str]:
    """Split a SQL script into complete statements, comments kept with what follows them.

    Uses `sqlite3.complete_statement`, which is SQLite's own `sqlite3_complete()` — it
    already knows that a semicolon inside a string literal or a comment does not end a
    statement. Splitting on ";" by hand would be a guess that happens to work on today's
    file; this is the real thing, and it stays correct when someone edits that file.
    """
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise RuntimeError(
            f"{SCHEMA_PATH.name} ends with an incomplete statement — a missing semicolon: "
            f"{buffer.strip()[:120]!r}"
        )
    return statements


def _split_schema(schema_text: str, staging: str) -> tuple[str, list[str]]:
    """(the CREATE TABLE for `titles`, renamed to `staging`) and (everything else).

    "Everything else" is the indexes and the `user_version` stamp, replayed inside the
    rebuild's transaction so the swap and the things that make the swapped table CORRECT —
    the UNIQUE index that means "already on your list" above all — commit together or not
    at all.
    """
    create, others = None, []
    for statement in _statements(schema_text):
        stripped = _strip_comments(statement)
        match = _CREATE_TITLES.search(stripped) if create is None else None
        if match:
            # The match was found on the COMMENT-FREE text, so a future comment that happens
            # to contain the literal "CREATE TABLE titles" can never be mistaken for the real
            # DDL — that text does not exist any more by the time `.search` runs. The span is
            # then applied to the RAW statement rather than re-matched there, because
            # `_CREATE_TITLES.subn` on raw text would find its OWN first hit — which, for a
            # comment written before the real CREATE TABLE, is the comment, not the DDL below
            # it. `_strip_comments` is length-preserving for exactly this reason: the span
            # names the identical characters in both strings, so no offset math is needed.
            start, end = match.span()
            assert statement[start:end] == stripped[start:end], (
                f"a comment inside the CREATE TABLE statement in {SCHEMA_PATH.name} shifted "
                "the match — refusing to guess which part is really the DDL"
            )
            create = statement[:start] + match.expand(rf'\1"{staging}"') + statement[end:]
            # Rewrite only the statement's own table name. Anchored to the CREATE TABLE
            # token, and the IF NOT EXISTS is dropped deliberately: staging must never
            # silently reuse a table that is already there.
            if f'"{staging}"' not in create:
                raise RuntimeError(f"could not rename the `titles` CREATE TABLE in {SCHEMA_PATH.name}")
        else:
            others.append(statement)
    if create is None:
        raise RuntimeError(f"{SCHEMA_PATH.name} has no CREATE TABLE for `titles`")
    return create, others


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, name: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")').fetchall()]


# ── the T-16 rebuild ─────────────────────────────────────────────────────────────────────
#
# WHY THIS EXISTS AT ALL.
# `bootstrap` applies schema.sql on every boot and every statement in it is
# `IF NOT EXISTS`. On a database that already has `titles`, the CREATE is a no-op — so the
# CHECK constraints it declares are the ones from the boot that first created the file, and
# editing them in schema.sql changes nothing. The owner's database was verified to still
# carry `CHECK (kind IN ('anime','movie','live-action','game'))` long after the file said
# otherwise. SQLite cannot ALTER a CHECK. Create-copy-drop-rename is the only route.
#
# WHAT MAKES IT SAFE.
# One transaction. `titles` — the original, the owner's actual list — is not touched until
# a complete copy exists beside it and has been counted. Anything at all going wrong rolls
# the whole thing back to a database that still has his list in it. A process killed at any
# point does the same, because that is what a transaction IS; the interrupt tests exist
# because a guard nobody has watched fail is not a guard.
#
# THE FOREIGN-KEY GOTCHA.
# SQLite's own table-rebuild procedure requires `PRAGMA foreign_keys=OFF` around the swap,
# and `_connect` above turns them ON for every connection this app opens. The pragma is
# ALSO a silent no-op inside a transaction, so it has to be flipped before BEGIN and put
# back after COMMIT — and the flip is verified below rather than assumed, because a no-op
# that returns no error is exactly the kind of thing that goes unnoticed for a year.
# Nothing references `titles` today, so this changes no behaviour now; it is here so the
# rebuild is still correct on the day T-9's or T-10's child tables do.


def _rebuild_titles(conn: sqlite3.Connection, schema_text: str) -> int:
    """Rebuild `titles` with the constraints schema.sql currently declares. Returns rows kept."""
    create_staging, others = _split_schema(schema_text, STAGING_TABLE)

    previous_foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise RuntimeError(
            "PRAGMA foreign_keys = OFF did not take effect — a table rebuild cannot be done "
            "safely with them on. This happens when the pragma is issued inside a "
            "transaction, where SQLite ignores it without raising."
        )

    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _table_exists(conn, STAGING_TABLE):
                conn.execute(f'DROP TABLE "{STAGING_TABLE}"')
            conn.execute(create_staging)

            # Copy every column BY NAME, both sides. `INSERT INTO new SELECT * FROM old`
            # would be shorter and would silently shift every value one column left the
            # first time somebody inserts a column into the middle of schema.sql — column
            # ORDER is not a contract, column NAMES are.
            old_columns = _columns(conn, "titles")
            new_columns = _columns(conn, STAGING_TABLE)
            shared = [column for column in new_columns if column in old_columns]
            lost = [column for column in old_columns if column not in new_columns]
            if lost:
                raise RuntimeError(
                    f"refusing to rebuild `titles`: the new schema has no column(s) {lost} "
                    "that the existing table has. That would silently discard data. Add the "
                    "column back to schema.sql, or write a deliberate migration for it."
                )

            named = ", ".join(f'"{column}"' for column in shared)
            before = conn.execute('SELECT COUNT(*) FROM "titles"').fetchone()[0]
            conn.execute(
                f'INSERT INTO "{STAGING_TABLE}" ({named}) SELECT {named} FROM "titles"'
            )
            copied = conn.execute(f'SELECT COUNT(*) FROM "{STAGING_TABLE}"').fetchone()[0]
            if copied != before:
                raise RuntimeError(
                    f"refusing to swap: copied {copied} rows out of {before}. Rolling back."
                )

            # AUTOINCREMENT's high-water mark. Without this the rebuilt table restarts ids
            # from max(id), so the next title added would reuse the id of one he deleted —
            # a stale bookmark or an open tab would then point at a different title.
            sequence_row = conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = 'titles'"
            ).fetchone()
            sequence = sequence_row[0] if sequence_row else None

            conn.execute('DROP TABLE "titles"')   # takes its indexes with it
            conn.execute(f'ALTER TABLE "{STAGING_TABLE}" RENAME TO "titles"')

            # The indexes and the `user_version` stamp, from the same file, inside the same
            # transaction — so the table and the UNIQUE index that makes "already on your
            # list" work can never be committed apart from one another.
            for statement in others:
                conn.execute(statement)

            if sequence is not None:
                updated = conn.execute(
                    "UPDATE sqlite_sequence SET seq = ? WHERE name = 'titles'", (sequence,)
                ).rowcount
                if not updated:
                    conn.execute(
                        "INSERT INTO sqlite_sequence (name, seq) VALUES ('titles', ?)", (sequence,)
                    )

            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"refusing to swap: foreign key violations {violations!r}")

            conn.execute("COMMIT")
        except BaseException:
            # Some SQLite errors (SQLITE_FULL, SQLITE_IOERR, SQLITE_BUSY on some paths) roll
            # the transaction back themselves before this handler ever runs. A bare ROLLBACK
            # then raises "cannot rollback - no transaction is active" from inside this
            # `except`, and THAT is what propagates — the real error that stopped the
            # migration is gone from the traceback. The data is already safe either way (the
            # transaction is rolled back one way or the other); this guard is for diagnosis,
            # not correctness.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if previous_foreign_keys else 'OFF'}")

    return copied


def _recover_staging(conn: sqlite3.Connection) -> str | None:
    """Clear debris from a rebuild whose transaction did not survive. Normally a no-op.

    A committed database can never contain the staging table: the rebuild drops it before it
    commits. So reaching here means atomicity itself was lost — a corrupted journal, a
    hand-edited file. It is handled anyway, and NOT by guessing, because the failure it
    prevents is the silent one: `titles` missing and every row sitting in a table nothing
    looks at, while `bootstrap` cheerfully creates a new empty `titles` beside it and the
    app opens on an empty list.

    Which table is authoritative is not a judgement call, it is the order of operations:
    the rebuild drops `titles` only after staging holds a counted, complete copy, and
    renames staging only after that. So `titles` present means `titles` is the original;
    `titles` absent means staging is the finished copy.
    """
    if not _table_exists(conn, STAGING_TABLE):
        return None

    if _table_exists(conn, "titles"):
        conn.execute(f'DROP TABLE "{STAGING_TABLE}"')
        logger.warning(
            "media-list: dropped leftover %s — an interrupted rebuild whose rollback was "
            "lost. `titles` is intact and was left untouched.", STAGING_TABLE,
        )
        return "dropped"

    conn.execute(f'ALTER TABLE "{STAGING_TABLE}" RENAME TO "titles"')
    logger.warning(
        "media-list: recovered `titles` from %s — an interrupted rebuild left the finished "
        "copy in place but never renamed it.", STAGING_TABLE,
    )
    return "recovered"


def migrate(conn: sqlite3.Connection, schema_text: str | None = None) -> str:
    """Bring an existing `titles` table up to `SCHEMA_VERSION`. Returns what it did.

    One of: `fresh` (no table yet — schema.sql is about to build it, already correct),
    `current` (nothing to do), `rebuilt`, or `recovered+…` when debris was cleared first.

    IDEMPOTENT BY CONSTRUCTION. The gate is `PRAGMA user_version`, and the rebuild stamps
    the new value INSIDE its own transaction (via schema.sql's own PRAGMA), so the version
    and the table shape it describes are committed together. There is no window in which a
    database claims to be migrated but is not, and none in which it is migrated but says it
    is not — which is what a boot-time migration has to guarantee to be safe to run forever.
    """
    if conn.in_transaction:
        raise RuntimeError("migrate() needs a connection with no transaction open")
    if schema_text is None:
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")

    # Explicit transactions only, so BEGIN IMMEDIATE and the pragmas around it mean what
    # they say. Python's default mode opens one implicitly before a write and would put the
    # `foreign_keys` pragma inside a transaction, where SQLite ignores it silently.
    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        recovered = _recover_staging(conn)
        prefix = f"{recovered}+" if recovered else ""

        if not _table_exists(conn, "titles"):
            return prefix + "fresh"

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return prefix + "current"

        rows = _rebuild_titles(conn, schema_text)
        logger.info(
            "media-list: rebuilt `titles` for schema version %s (was %s), %s row(s) kept",
            SCHEMA_VERSION, version, rows,
        )
        return prefix + "rebuilt"
    finally:
        conn.isolation_level = previous_isolation


def bootstrap(db_path: Path | None = None) -> Path:
    """Create the database if it is missing and bring the schema up to date.

    Idempotent: safe to call on every boot, on an empty directory or a populated database.
    Returns the resolved path so callers can report where the data actually landed.
    """
    path = Path(db_path) if db_path else config.db_path
    # sqlite3.connect() will not create a missing parent directory — it raises. `data/` is
    # gitignored, so a fresh clone genuinely has no such directory and this line is the
    # difference between a working first boot and a stack trace.
    path.parent.mkdir(parents=True, exist_ok=True)
    config.art_dir.mkdir(parents=True, exist_ok=True)

    # `with sqlite3.connect(...)` manages the TRANSACTION, not the connection — it does not
    # close anything. Closing explicitly keeps a repeated bootstrap (tests, reloads) from
    # accumulating open handles on the database file.
    conn = _connect(path)
    try:
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
        # BEFORE schema.sql, and it has to stay before it: schema.sql stamps `user_version`,
        # which is the very flag `migrate` reads to decide whether this database predates
        # the rebuild. Applying the schema first would stamp every old database as current
        # and the migration would never run on the one file it exists for.
        migrate(conn, schema_text)
        conn.executescript(schema_text)
        conn.commit()
    finally:
        conn.close()
    return path


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """A connection for one unit of work, committed on success, rolled back on error."""
    conn = _connect(config.db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write and return the last inserted row id."""
    with connection() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid
