"""AC2 — import atomicity (T-10 AC7): a failing row commits NOTHING, not "everything before it".

`import_commit` runs every insert of a batch on ONE connection inside ONE transaction
specifically so a failure anywhere leaves the database exactly as it was — T-10's own
evidence describes proving this by sabotaging the third insert of four with "a simulated
disk failure". This file's sabotage is a schema CHECK violation (an out-of-enum `kind`)
instead, because it needs no mocking beyond what `fake_source` already provides — the
mechanism under test is `backend/db.py::connection()`'s rollback-on-exception, not the
specific way a row fails.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from starlette.testclient import TestClient

from backend.main import app

#: T-15 AC4's batch. Large enough that the sabotaged row is reached long after the
#: transaction started writing, which is the whole point: rows 0-249 ARE inserted, and the
#: only thing that proves this was a transaction is that they are gone afterwards.
BIG_BATCH = 500
SABOTAGE_AT = 250


def _entry(source_id: str, title: str, kind: str) -> dict:
    return {
        "row": {
            "title": title, "year": 2020, "kind": kind, "why": None, "status": None,
            "stars": None, "queue_position": None, "tmdb_id": None, "igdb_id": None,
            "imdb_id": None, "added_at": None, "watched_at": None, "review": None,
        },
        "chosen": {"source": "tmdb", "source_id": source_id, "media_type": "movie",
                   "title": title, "year": 2020, "kind": kind},
    }


def test_commit_with_no_bad_rows_adds_everything(client, fake_source):
    for i in range(1, 4):
        fake_source("tmdb", f"good-{i}", title=f"Good {i}", kind="movie", year=2020)
    entries = [_entry(f"good-{i}", f"Good {i}", "movie") for i in range(1, 4)]

    resp = client.post("/api/import/commit", json={"entries": entries})
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {"added": 3, "skipped": 0, "failed": 0}
    assert len(client.get("/api/titles").json()) == 3


def test_a_failing_row_commits_nothing_not_even_the_rows_before_it(seed, fake_source):
    seed(source="tmdb", source_id="existing-1", title="Existing One", status="queued", queue_position=10)
    seed(source="tmdb", source_id="existing-2", title="Existing Two", status="queued", queue_position=20)

    entries = []
    for i in range(1, 5):
        # Row 3's `kind` is outside the schema's CHECK (anime/movie/live-action/game) --
        # the third of four, same shape as T-10's own sabotage.
        kind = "movie" if i != 3 else "not-a-real-kind"
        fake_source("tmdb", f"new-{i}", title=f"New Title {i}", kind=kind, year=2020)
        entries.append(_entry(f"new-{i}", f"New Title {i}", kind))

    with TestClient(app, raise_server_exceptions=False) as sabotaged_client:
        before = sabotaged_client.get("/api/titles").json()
        assert len(before) == 2

        resp = sabotaged_client.post("/api/import/commit", json={"entries": entries})
        assert resp.status_code >= 500  # the CHECK violation was not swallowed into a 200

        after = sabotaged_client.get("/api/titles").json()

    # Rows 1 and 2 of the batch DID insert successfully before row 3 blew up -- the only
    # thing that proves this was a transaction and not "insert until it breaks" is that
    # they are gone too.
    assert len(after) == 2
    assert {t["title"] for t in after} == {"Existing One", "Existing Two"}
    assert "New Title 1" not in {t["title"] for t in after}
    assert "New Title 2" not in {t["title"] for t in after}


# ── T-15 AC4 — atomicity holds UNDER CONCURRENCY ──────────────────────────────────────────
#
# T-15 made `import_commit`'s FETCH phase concurrent. The insert loop below it did not move:
# it is still one transaction on one connection, walking `prepared` in order. This is the
# clause that vetoes lean, so it is proven at 500 rows rather than 4 — and it asserts that
# the fetch phase really did overlap, because "atomicity holds under concurrency" proven
# against a fetch phase that quietly ran sequentially would prove nothing at all.


def _record(source_id: str, title: str, kind: str) -> dict:
    return {
        "source": "tmdb", "source_id": source_id, "media_type": "movie", "title": title,
        "original_title": None, "year": 2020, "kind": kind, "summary": None,
        "poster_url": None, "backdrop_url": None, "poster_path": None, "backdrop_path": None,
        "genres": [], "detail": {}, "imdb_id": None, "anilist_id": None,
    }


def test_a_failing_row_in_a_large_concurrent_batch_still_commits_nothing(seed, monkeypatch):
    """T-15 AC4 — force a failure mid-commit inside a large batch; the row count is unchanged."""
    import backend.main as main_module

    seed(source="tmdb", source_id="existing-1", title="Existing One", status="queued", queue_position=10)
    seed(source="tmdb", source_id="existing-2", title="Existing Two", status="queued", queue_position=20)

    fetches = {"count": 0, "in_flight": 0, "peak": 0}

    async def fetch(source: str, source_id: str, media_type: str | None = None) -> dict:
        fetches["count"] += 1
        fetches["in_flight"] += 1
        fetches["peak"] = max(fetches["peak"], fetches["in_flight"])
        try:
            # A stand-in round trip. Without an await there is nothing to overlap and the
            # "was it concurrent" assertion below could not fail even if it should.
            await asyncio.sleep(0.002)
            index = int(str(source_id).rsplit("-", 1)[1])
            # Row SABOTAGE_AT's `kind` is outside the schema's CHECK
            # (anime/movie/live-action/game) -- the same sabotage the four-row case uses,
            # placed halfway through a 500-row batch.
            kind = "not-a-real-kind" if index == SABOTAGE_AT else "movie"
            return _record(str(source_id), f"New Title {index}", kind)
        finally:
            fetches["in_flight"] -= 1

    monkeypatch.setattr(main_module, "_fetch", fetch)
    entries = [_entry(f"new-{i}", f"New Title {i}", "movie") for i in range(BIG_BATCH)]

    with TestClient(app, raise_server_exceptions=False) as sabotaged_client:
        before = sabotaged_client.get("/api/titles").json()
        assert len(before) == 2

        resp = sabotaged_client.post("/api/import/commit", json={"entries": entries})
        assert resp.status_code >= 500  # the CHECK violation was not swallowed into a 200

        after = sabotaged_client.get("/api/titles").json()

    assert fetches["count"] == BIG_BATCH, "not every entry was fetched"
    assert fetches["peak"] > 1, (
        "the fetch phase never had two fetches in flight, so this run proves atomicity under "
        "a SEQUENTIAL fetch — which is not what AC4 claims. The concurrency is gone."
    )

    # THE ASSERTION THE TICKET TURNS ON. The transaction had already inserted rows 0-249
    # before row 250 blew up; the row count being unchanged is the only thing that
    # distinguishes a transaction from "insert until it breaks".
    assert len(after) == len(before) == 2
    assert {t["title"] for t in after} == {"Existing One", "Existing Two"}
    assert not [t for t in after if t["title"].startswith("New Title")]


def test_the_sabotaged_row_really_is_reached_only_after_hundreds_have_been_written(seed, monkeypatch):
    """The guard on the guard: prove the failure happens INSIDE the transaction, not before it.

    If `_fetch` had failed instead, `import_commit` would have recorded a `failures` entry and
    committed the other 499 rows quite correctly — and the test above would still have seen
    "nothing was added" while proving nothing about rollback. So: count the inserts that
    actually executed before the exception.
    """
    import backend.db as db_module
    import backend.main as main_module

    inserted = {"count": 0}
    real_connection = db_module.connection

    async def fetch(source: str, source_id: str, media_type: str | None = None) -> dict:
        index = int(str(source_id).rsplit("-", 1)[1])
        kind = "not-a-real-kind" if index == SABOTAGE_AT else "movie"
        return _record(str(source_id), f"New Title {index}", kind)

    def trace(statement: str) -> None:
        if statement.strip().upper().startswith("INSERT INTO TITLES"):
            inserted["count"] += 1

    @contextmanager
    def counting_connection():
        # `sqlite3.Connection` has no instance dict, so `conn.execute = ...` is an
        # AttributeError, not a wrapper. `set_trace_callback` is sqlite3's own seam for this
        # and fires per statement executed, the failing one included.
        with real_connection() as conn:
            conn.set_trace_callback(trace)
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)

    monkeypatch.setattr(main_module, "_fetch", fetch)
    monkeypatch.setattr(main_module, "connection", counting_connection)

    entries = [_entry(f"new-{i}", f"New Title {i}", "movie") for i in range(BIG_BATCH)]
    with TestClient(app, raise_server_exceptions=False) as sabotaged_client:
        resp = sabotaged_client.post("/api/import/commit", json={"entries": entries})
        assert resp.status_code >= 500
        after = sabotaged_client.get("/api/titles").json()

    assert inserted["count"] == SABOTAGE_AT + 1, (
        f"{inserted['count']} INSERTs ran before the failure; expected {SABOTAGE_AT + 1} "
        "(rows 0..249 succeeded, row 250 raised). If this is 0 or 1 the sabotage moved out "
        "of the transaction and the rollback is no longer what is being tested."
    )
    assert after == [], f"{len(after)} rows survived a rolled-back transaction"
