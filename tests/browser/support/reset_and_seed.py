"""Wipe `titles` and insert exactly the rows a browser spec asked for.

Playwright specs are JavaScript and cannot import tests/conftest.py's `insert_title`
fixture directly, so this is that same pattern (insert straight into the database,
bypassing the API and every network source) re-exposed as a one-shot subprocess: read a
JSON array of row overrides on stdin, write them, print the new ids as a JSON array.

Invoked with MEDIA_LIST_DB already set (by global-setup.js, inherited from the Playwright
runner's own environment) to the scratch database it created — never data/media-list.db.
The assert below is belt-and-suspenders, same reasoning as tests/conftest.py's own: better
a loud crash here than a silent write to the owner's real 14-title list.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    db_path = os.environ.get("MEDIA_LIST_DB", "")
    assert "media-list-pw-" in db_path, (
        f"refusing to touch a database that doesn't look like a Playwright scratch db: {db_path!r}"
    )

    # Import AFTER the environment is confirmed scratch — same ordering rule as
    # tests/conftest.py (backend.config resolves MEDIA_LIST_DB at import time).
    from backend.db import connection
    from backend.titles import now

    rows = json.loads(sys.stdin.read())

    ids: list[int] = []
    with connection() as conn:
        conn.execute("DELETE FROM titles")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'titles'")

        for index, overrides in enumerate(rows):
            fields = {
                "source": "tmdb",
                "source_id": f"pw-seed-{index}",
                "imdb_id": None,
                "anilist_id": None,
                "title": "Test Title",
                "original_title": None,
                "year": 2020,
                "kind": "movie",
                "summary": None,
                "poster_path": None,
                "backdrop_path": None,
                "genres": "[]",
                "detail": "{}",
                "why": None,
                "status": "queued",
                "stars": None,
                "review": None,
                "queue_position": (index + 1) * 10,
                "added_at": now(),
                "watched_at": None,
            }
            fields.update(overrides)
            if not isinstance(fields["genres"], str):
                fields["genres"] = json.dumps(fields["genres"])
            if not isinstance(fields["detail"], str):
                fields["detail"] = json.dumps(fields["detail"])

            columns = list(fields)
            placeholders = ",".join("?" for _ in columns)
            cursor = conn.execute(
                f"INSERT INTO titles ({','.join(columns)}) VALUES ({placeholders})",
                tuple(fields[c] for c in columns),
            )
            ids.append(cursor.lastrowid)

    print(json.dumps(ids))


if __name__ == "__main__":
    main()
