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

from starlette.testclient import TestClient

from backend.main import app


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
