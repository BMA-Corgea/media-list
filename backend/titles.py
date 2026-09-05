"""Reading and writing rows of the list.

One place decodes the JSON-in-TEXT columns, so no caller has to remember which fields are
strings that happen to hold JSON.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

JSON_COLUMNS = ("genres", "detail")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def serialise(row: sqlite3.Row) -> dict:
    record = dict(row)
    for column in JSON_COLUMNS:
        raw = record.get(column)
        record[column] = json.loads(raw) if raw else ([] if column == "genres" else {})

    # The outbound link differs by kind and is derived, never stored: games have no IMDb
    # entry at all, so a single "link" column would have been null half the time.
    if record.get("imdb_id"):
        record["link"] = f"https://www.imdb.com/title/{record['imdb_id']}/"
        record["link_label"] = "IMDb"
    elif (record.get("detail") or {}).get("igdb_url"):
        record["link"] = record["detail"]["igdb_url"]
        record["link_label"] = "IGDB"
    else:
        record["link"] = None
        record["link_label"] = None
    return record
