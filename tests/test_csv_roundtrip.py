"""AC2 / AC7 — CSV export/import against the contract README.md publishes (T-10's evidence).

The header below is copied verbatim from README.md's "The export format" section. If that
document and `backend/csvio.COLUMNS` ever drift, this test is the tripwire — the README is
"final" per its own words, and `csvio.py`'s docstring says it "must not drift from that
document."
"""

from __future__ import annotations

import csv
import io

from tests.factories import preview_result

def _readme_export_header(repo_root) -> str:
    """The export header as README.md actually publishes it, read from the document.

    This used to be a string copied into this file by hand. That makes a weaker tripwire
    than it looks: it catches `csvio` drifting from the COPY, and is perfectly happy when
    `csvio` and the copy are updated together and the README is left behind — which is the
    drift that matters, because the README is the half the owner was told to rely on.
    T-16 added a column to this contract and this is the test that has to make the two move
    together, so it now reads the real document.
    """
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    headers = [line.strip() for line in text.splitlines()
               if line.strip().startswith("title,year,kind,why,status,")]
    assert len(headers) == 1, (
        f"expected exactly one export header line in README.md, found {len(headers)}: {headers}"
    )
    return headers[0]


def test_export_header_matches_the_readme_contract(client, repo_root):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200
    header_line = resp.text.split("\r\n", 1)[0]
    assert header_line == _readme_export_header(repo_root)


def test_csvio_columns_are_exactly_what_the_readme_publishes(repo_root):
    """The other half of the same contract: `csvio.COLUMNS` IS the README's header.

    `csvio.py`'s docstring says the column list "must not drift from that document". This
    is that sentence, enforced — in the direction the hand-copied constant could not check.
    """
    from backend import csvio

    assert ",".join(csvio.COLUMNS) == _readme_export_header(repo_root)


def test_the_readme_documents_every_column_it_publishes(repo_root):
    """Every column in the header has a row in one of the README's own column tables.

    A column added to the contract but never described is the failure this catches: the
    header is what a chatbot is told to emit, the tables are what tell a human what to put
    in it, and `isbn` arriving in one but not the other would make the document quietly
    wrong rather than loudly wrong.
    """
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    for column in _readme_export_header(repo_root).split(","):
        assert f"`{column}`" in text, (
            f"README.md publishes the column {column!r} in the export header but never "
            f"documents it — no `{column}` appears anywhere in the prose or the tables."
        )


def test_export_is_rfc4180_quoted_and_utf8(client, seed):
    seed(
        source="tmdb", source_id="1", title='Say "watch it twice", he said',
        why="has, a comma", status="queued", queue_position=10,
    )
    resp = client.get("/api/export.csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows[0]["title"] == 'Say "watch it twice", he said'
    assert rows[0]["why"] == "has, a comma"


def test_game_row_carries_igdb_id_and_blank_tmdb_id(client, seed):
    seed(source="igdb", source_id="9999", title="A Game", kind="game", status="queued", queue_position=10)
    resp = client.get("/api/export.csv")
    row = next(csv.DictReader(io.StringIO(resp.text)))
    assert row["igdb_id"] == "9999"
    assert row["tmdb_id"] == ""


def test_screen_row_carries_tmdb_id_and_blank_igdb_id(client, seed):
    seed(source="tmdb", source_id="603", title="The Matrix", kind="movie", status="queued", queue_position=10)
    resp = client.get("/api/export.csv")
    row = next(csv.DictReader(io.StringIO(resp.text)))
    assert row["tmdb_id"] == "603"
    assert row["igdb_id"] == ""


def test_empty_why_exports_as_a_blank_field_not_a_literal_none(client, seed):
    seed(source="tmdb", source_id="1", title="No Reason Given", why=None, status="queued", queue_position=10)
    resp = client.get("/api/export.csv")
    row = next(csv.DictReader(io.StringIO(resp.text)))
    assert row["why"] == ""


def _seed_a_small_list(seed):
    seed(source="tmdb", source_id="601", title="Movie One", kind="movie", year=2001,
         why="recommended", status="queued", queue_position=10)
    seed(source="tmdb", source_id="602", title="Show Two", kind="live-action", year=2010,
         status="queued", queue_position=20)
    seed(source="igdb", source_id="701", title="Game Three", kind="game", year=2015,
         status="seen", stars=4, review="great", watched_at="2026-01-01T00:00:00+00:00")


def test_round_trip_preview_recognises_every_row_as_a_duplicate(client, seed):
    _seed_a_small_list(seed)
    csv_text = client.get("/api/export.csv").text

    resp = client.post("/api/import/preview", json={"text": csv_text})
    assert resp.status_code == 200
    body = preview_result(resp)
    assert body["problems"] == []
    assert body["counts"] == {"duplicate": 3}
    assert all(row["state"] == "duplicate" for row in body["rows"])
    # No search needed at all -- every row carried its own id.
    assert all(row["candidates"] == [] for row in body["rows"])


def test_round_trip_commit_adds_nothing_and_the_list_is_unchanged(client, seed, fake_source):
    _seed_a_small_list(seed)
    before = client.get("/api/titles").json()
    assert len(before) == 3

    csv_text = client.get("/api/export.csv").text
    preview = preview_result(client.post("/api/import/preview", json={"text": csv_text}))

    # import_commit calls _fetch() for every entry before it ever checks for a duplicate in
    # the database (network calls happen outside the write transaction, by design) -- so
    # each id round-tripped through the CSV needs a stub, matching what is already stored.
    fake_source("tmdb", "601", title="Movie One", kind="movie", year=2001)
    fake_source("tmdb", "602", title="Show Two", kind="live-action", year=2010)
    fake_source("igdb", "701", title="Game Three", kind="game", year=2015)

    commit = client.post("/api/import/commit", json={"entries": preview["rows"]})
    assert commit.status_code == 200
    result = commit.json()
    assert result["added"] == []
    assert result["counts"] == {"added": 0, "skipped": 3, "failed": 0}

    after = client.get("/api/titles").json()
    assert len(after) == 3
    fingerprint = lambda rows: sorted(  # noqa: E731
        (r["title"], r["year"], r["kind"], r["status"], r["stars"], r["queue_position"], r["review"])
        for r in rows
    )
    assert fingerprint(before) == fingerprint(after)


def test_readmes_own_starter_csv_parses_with_no_problems(client, monkeypatch):
    """The exact block published under "The starter format" in README.md.

    None of these rows carry an id, so `import_preview` searches for each one — stub
    `tmdb.search`/`igdb.search` themselves (not HTTP) with one clean match per query. The
    goal here is the *parser and resolver plumbing* (README's own CSV survives with zero
    `problems`, nothing silently dropped), not search-ranking accuracy, which is exercised
    directly against `csvio.score` elsewhere in spirit and is not this file's job.
    """
    import backend.main as main_module

    async def fake_search(query: str) -> list[dict]:
        return [{
            "source": "tmdb", "source_id": query, "media_type": "movie",
            "title": query, "original_title": None, "year": None, "kind": None,
            "summary": None, "poster_url": None, "backdrop_url": None, "popularity": 0,
        }]

    async def no_books(query: str) -> list[dict]:
        """Open Library answers, and answers with nothing. There are no books in the
        starter CSV, and a source that is always on must still be STUBBED — it is the one
        source with no credentials to be missing, so nothing else would stop it."""
        return []

    monkeypatch.setattr(main_module.tmdb, "search", fake_search)
    monkeypatch.setattr(main_module.igdb, "search", fake_search)
    monkeypatch.setattr(main_module.openlibrary, "search", no_books)

    starter_csv = (
        "title,year,kind,why\n"
        "Cowboy Bebop,1998,anime,Everyone says the jazz soundtrack alone is worth it\n"
        "Perfect Blue,1997,anime,Satoshi Kon — supposedly the one Aronofsky lifted from\n"
        "The Thing,1982,movie,Practical effects that still hold up\n"
        "Andor,2022,live-action,The one Star Wars thing adults keep recommending\n"
        'Hollow Knight,2017,game,"Apparently the best 15 dollars anyone has ever spent"\n'
        "Disco Elysium,2019,game,A detective RPG where you can lose an argument with your own brain\n"
        "Frieren: Beyond Journey's End,2023,anime,\n"
    )
    resp = client.post("/api/import/preview", json={"text": starter_csv})
    assert resp.status_code == 200
    body = preview_result(resp)
    assert body["problems"] == []
    assert len(body["rows"]) == 7
    titles = [r["row"]["title"] for r in body["rows"]]
    assert "Frieren: Beyond Journey's End" in titles
    # Every row is unmatched/choose/matched -- never dropped, and never crashes on the
    # trailing-empty-why row or the quoted comma-containing field.
    assert all(r["state"] in ("unmatched", "choose", "matched", "duplicate") for r in body["rows"])
