"""SQLite access and the self-creating database.

The whole bootstrap story is here. There is no migration command to run and no server to
install: opening the app is what builds the database. Deleting `data/` and restarting is a
supported action, and it is how this ticket is tested.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Rows reference nothing yet, but T-9 and T-10 will; turning this on now means the
    # constraint exists from the first row rather than being retrofitted over live data.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the carousel read while an import writes (T-10) without either blocking.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


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
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
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
