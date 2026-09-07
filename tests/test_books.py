"""T-16 — books, end to end, with Open Library stubbed.

Open Library is the only source in this app that needs no credentials, which makes it the
only one whose real client would work on a machine with an empty `.env`. Every test here
therefore stubs it explicitly; `conftest.py::no_network` is the backstop underneath, and
`test_the_stub_is_what_answers_not_the_internet` is the proof that the backstop is armed.
"""

from __future__ import annotations

import csv
import io
import json

import httpx
import pytest

from backend import csvio
from backend.sources import openlibrary
from tests.factories import preview_result

#: One work, in the shape `search.json` really returns — checked against the live API.
DISPOSSESSED = {
    "key": "/works/OL59863W",
    "title": "The Dispossessed",
    "author_name": ["Ursula K. Le Guin"],
    "first_publish_year": 1974,
    "cover_i": 6979680,
    "edition_count": 75,
    "subject": ["Anarchism", "Science fiction", "Utopias"],
    "isbn": ["0061054887", "9780061054884", "9780575079038"],
    "number_of_pages_median": 352,
}

LATHE = {
    "key": "/works/OL59858W", "title": "The Lathe of Heaven",
    "author_name": ["Ursula K. Le Guin"], "first_publish_year": 1971,
    "cover_i": 26458, "edition_count": 40,
}


@pytest.fixture
def openlibrary_api(monkeypatch):
    """Answer openlibrary.org from a table, and record what was asked.

    A real `httpx` transport rather than a patched `search()`, so everything under test —
    the URL, the `fields` list, the rate limiter, the JSON parsing — is genuinely exercised.
    """
    calls: list[str] = []
    state = {"docs": [DISPOSSESSED], "description": "Shevek, a brilliant physicist.",
             "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if state["status"] != 200:
            return httpx.Response(state["status"], json={})
        if request.url.path == "/search.json":
            query = dict(request.url.params).get("q", "")
            docs = state["docs"]
            # `key:` and `isbn:` are exact lookups; anything else is a title search.
            if query.startswith("key:"):
                docs = [d for d in docs if d["key"] == query.split("key:", 1)[1]]
            elif query.startswith("isbn:"):
                wanted = query.split("isbn:", 1)[1]
                docs = [d for d in docs if wanted in (d.get("isbn") or [])]
            return httpx.Response(200, json={"numFound": len(docs), "docs": docs})
        if request.url.path.endswith(".json") and "/works/" in request.url.path:
            return httpx.Response(200, json={"description": state["description"]})
        raise AssertionError(f"unexpected Open Library URL: {request.url}")

    def stubbed_client(*_a, **_k) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(openlibrary, "client", stubbed_client)
    state["calls"] = calls
    return state


# ── the source itself ────────────────────────────────────────────────────────────────────


def test_open_library_is_always_available_because_it_has_no_key():
    """The structurally new thing. Every other source gates on credentials; this one has
    nothing to be missing, so "configured" and "usable" stopped being one question."""
    assert openlibrary.available() is True


def test_a_work_key_becomes_a_bare_source_id():
    assert openlibrary.work_id("/works/OL59863W") == "OL59863W"
    assert openlibrary.work_id("OL59863W") == "OL59863W"


def test_covers_are_addressed_by_id_which_is_the_unthrottled_form():
    assert openlibrary.cover_url(6979680) == "https://covers.openlibrary.org/b/id/6979680-L.jpg"
    assert openlibrary.cover_url(None) is None


def test_search_returns_book_kind_candidates(openlibrary_api, run_async):
    openlibrary_api["docs"] = [DISPOSSESSED, LATHE]
    results = run_async(openlibrary.search("Le Guin"))
    assert [r["title"] for r in results] == ["The Dispossessed", "The Lathe of Heaven"]
    assert {r["kind"] for r in results} == {"book"}
    assert {r["source"] for r in results} == {"openlibrary"}
    assert results[0]["source_id"] == "OL59863W"
    assert results[0]["year"] == 1974


def test_search_does_not_download_any_artwork(openlibrary_api, run_async, no_network):
    """Search is typed INTO. Caching a cover per keystroke would pull megabytes per
    character, which is why `/search` fills no cache and `/details` does."""
    results = run_async(openlibrary.search("Le Guin"))
    assert results[0]["poster_url"].startswith("https://covers.openlibrary.org/")
    assert not any("covers.openlibrary.org" in url for url in openlibrary_api["calls"])
    assert no_network == [], f"search reached the network for artwork: {no_network}"


def test_search_asks_for_no_isbn_field(openlibrary_api, run_async):
    """A well-published work carries a hundred ISBNs. Requesting them on every keystroke
    would make the typing path pay for the details path's data."""
    run_async(openlibrary.search("Le Guin"))
    assert "isbn" not in openlibrary_api["calls"][0]


def test_details_carries_author_subjects_isbn_and_the_description(openlibrary_api, run_async):
    record = run_async(openlibrary.details("OL59863W"))
    assert record["title"] == "The Dispossessed"
    assert record["kind"] == "book"
    assert record["detail"]["author"] == "Ursula K. Le Guin"
    assert record["detail"]["pages"] == 352
    assert record["detail"]["openlibrary_url"] == "https://openlibrary.org/works/OL59863W"
    assert record["genres"] == ["Anarchism", "Science fiction", "Utopias"]
    assert record["summary"].startswith("Shevek")
    assert record["imdb_id"] is None
    assert record["backdrop_url"] is None


def test_details_picks_one_isbn_deterministically(openlibrary_api, run_async):
    """A work has many editions and therefore many ISBNs, in no stable order. `[0]` would
    make the exported value flap between one export and the next."""
    first = run_async(openlibrary.details("OL59863W"))["isbn"]
    openlibrary_api["docs"] = [{**DISPOSSESSED, "isbn": list(reversed(DISPOSSESSED["isbn"]))}]
    second = run_async(openlibrary.details("OL59863W"))["isbn"]
    assert first == second == "9780061054884"
    assert len(first) == 13


def test_a_description_that_is_an_object_is_read_too(openlibrary_api, run_async):
    """Open Library returns this as a bare string OR as {"type":…, "value":…}, depending on
    how old the record is. Both are current in live data."""
    openlibrary_api["description"] = {"type": "/type/text", "value": "An object description."}
    assert run_async(openlibrary.details("OL59863W"))["summary"] == "An object description."


def test_a_missing_description_does_not_lose_the_book(openlibrary_api, run_async):
    openlibrary_api["description"] = None
    record = run_async(openlibrary.details("OL59863W"))
    assert record["summary"] is None
    assert record["title"] == "The Dispossessed"


def test_an_unknown_work_is_a_404_not_an_empty_record(openlibrary_api, run_async):
    from backend.sources.base import SourceError
    with pytest.raises(SourceError) as raised:
        run_async(openlibrary.details("OL_NOPE_W"))
    assert raised.value.status == 404
    assert raised.value.source == "openlibrary"


def test_an_upstream_failure_names_open_library(openlibrary_api, run_async):
    from backend.sources.base import SourceError
    openlibrary_api["status"] = 429
    with pytest.raises(SourceError) as raised:
        run_async(openlibrary.search("anything"))
    assert raised.value.source == "openlibrary"
    assert "rate limited" in raised.value.detail


def test_the_stub_is_what_answers_not_the_internet(run_async, no_network):
    """The backstop, checked. With no stub installed the real client must be the blocked
    one — this source has no credentials to be missing, so nothing else would stop it."""
    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(openlibrary.search("The Dispossessed"))
    assert any("openlibrary.org" in attempt for attempt in no_network)


# ── by_isbn: what makes a book round-trip exactly ────────────────────────────────────────


def test_an_isbn_resolves_to_the_work_that_holds_it(openlibrary_api, run_async):
    record = run_async(openlibrary.by_isbn("9780061054884"))
    assert record["source_id"] == "OL59863W"
    assert record["kind"] == "book"


def test_isbn_punctuation_is_tolerated(openlibrary_api, run_async):
    """Humans and half the web write ISBNs with hyphens; Open Library indexes them bare."""
    assert run_async(openlibrary.by_isbn("978-0-06-105488-4"))["source_id"] == "OL59863W"
    assert run_async(openlibrary.by_isbn(" 0061054887 "))["source_id"] == "OL59863W"


def test_an_isbn_nobody_carries_is_none_not_an_error(openlibrary_api, run_async):
    assert run_async(openlibrary.by_isbn("9999999999999")) is None
    assert run_async(openlibrary.by_isbn("")) is None


# ── /api/health tells the truth about a source with no key ───────────────────────────────


def test_health_reports_open_library_as_usable_and_as_needing_nothing(client):
    """`"openlibrary": true` under a map that used to mean "credentials found" would be a
    quiet lie. What each source IS and what each source NEEDS are published separately."""
    body = client.get("/api/health").json()
    assert body["sources"]["openlibrary"] is True
    assert body["needs_credentials"]["openlibrary"] is False
    assert body["needs_credentials"]["tmdb"] is True
    assert body["needs_credentials"]["igdb"] is True
    assert set(body["needs_credentials"]) == set(body["sources"])


# ── /api/search ──────────────────────────────────────────────────────────────────────────


def test_search_returns_books_and_names_the_sources_that_died(client, openlibrary_api, monkeypatch):
    """A dead source is reported BY NAME, never as an empty list — an empty list reads as
    "there are no matches", which is a lie told on the failed source's behalf. Books are the
    proof case now, because they are the results that still arrive when the others fall."""
    import backend.main as main_module
    from backend.sources.base import SourceError

    async def dead(query: str):
        raise SourceError("tmdb", "credentials rejected — check the key in .env", 401)

    monkeypatch.setattr(main_module.tmdb, "search", dead)
    monkeypatch.setattr(main_module.igdb, "search", dead)

    body = client.get("/api/search", params={"q": "The Dispossessed"}).json()
    assert [r["title"] for r in body["results"]] == ["The Dispossessed"]
    assert body["sources"]["openlibrary"] == {"ok": True, "count": 1}
    assert body["sources"]["tmdb"]["ok"] is False
    assert "credentials rejected" in body["sources"]["tmdb"]["error"]
    assert body["disabled"] == []


def test_a_source_that_dies_without_a_message_still_says_what_killed_it(client, openlibrary_api, monkeypatch):
    """Several httpx timeout exceptions stringify to the EMPTY string, so reporting
    `str(exc)` named the dead source and then gave no reason whatsoever — the exact silence
    the `sources` dict exists to break.

    Open Library is why this is not theoretical: it is the one source with no credential
    gate, so it is asked on every single search, and its connect times out often enough to
    see by hand (observed 1 in 3 against the live API from this machine, 2026-09-07).
    """
    import httpx
    import backend.main as main_module

    async def timed_out(query: str):
        raise httpx.ConnectTimeout("")

    assert str(httpx.ConnectTimeout("")) == "", "the premise of this test is that it is empty"
    monkeypatch.setattr(main_module.openlibrary, "search", timed_out)

    body = client.get("/api/search", params={"q": "The Dispossessed"}).json()
    assert body["sources"]["openlibrary"]["ok"] is False
    assert body["sources"]["openlibrary"]["error"] == "ConnectTimeout"


def test_open_library_is_consulted_even_with_no_credentials_at_all(client, openlibrary_api, monkeypatch):
    """The fresh-clone case: an empty .env used to mean a 503 and no search at all. Books
    need no key, so search now works and says which sources are switched off."""
    import backend.main as main_module
    monkeypatch.setattr(main_module.tmdb, "available", lambda: False)
    monkeypatch.setattr(main_module.igdb, "available", lambda: False)

    body = client.get("/api/search", params={"q": "The Dispossessed"}).json()
    assert [r["title"] for r in body["results"]] == ["The Dispossessed"]
    assert sorted(body["disabled"]) == ["igdb", "tmdb"]
    assert "openlibrary" not in body["disabled"]


# ── adding a book, the AC1 path ──────────────────────────────────────────────────────────


def test_a_book_is_added_like_anything_else(client, openlibrary_api):
    resp = client.post("/api/titles", json={
        "source": "openlibrary", "source_id": "OL59863W", "why": "Le Guin, finally",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "book"
    assert body["source"] == "openlibrary"
    assert body["isbn"] == "9780061054884"
    assert body["why"] == "Le Guin, finally"
    assert body["detail"]["author"] == "Ursula K. Le Guin"
    assert body["summary"].startswith("Shevek")
    assert body["link"] == "https://openlibrary.org/works/OL59863W"
    assert body["link_label"] == "Open Library"


def test_the_same_book_cannot_be_added_twice(client, openlibrary_api):
    """`(source, source_id)` is a work key, so all seventy-five printings are one row."""
    assert client.post("/api/titles", json={"source": "openlibrary", "source_id": "OL59863W"}).status_code == 201
    second = client.post("/api/titles", json={"source": "openlibrary", "source_id": "OL59863W"})
    assert second.status_code == 409
    assert "already on your list" in second.json()["detail"]["detail"]


def test_a_book_gets_read_not_finished_in_the_kind_map(repo_root):
    """`frontend/src/kinds.js` is the ONE place that decides a game is played and a film is
    watched. Without an entry a book would fall through to 'finished', which is nobody's
    word for what you do to a book.

    T-16 round 2, F8: this is a cheap tripwire, kept deliberately, but it never calls
    `verbFor` and never renders anything — it would stay green if `verbFor` stopped
    consulting this map entirely. The real assertion is
    `tests/browser/title.spec.js::"F8 — the mark-as-read verb is genuinely consulted..."`,
    which opens a book's title page and reads the actual rendered button and past-tense
    text."""
    kinds = (repo_root / "frontend" / "src" / "kinds.js").read_text(encoding="utf-8")
    book_line = [l for l in kinds.splitlines() if l.strip().startswith("book:")]
    assert book_line, "kinds.js has no `book` entry — a book would be 'finished'"
    assert "'read'" in book_line[0] and "Mark as read" in book_line[0]


# ── AC8: the CSV round trip ──────────────────────────────────────────────────────────────


@pytest.fixture
def quiet_screen_sources(monkeypatch):
    """TMDB and IGDB present, awake, and with nothing to say about books."""
    import backend.main as main_module

    async def nothing(query: str) -> list[dict]:
        return []

    monkeypatch.setattr(main_module.tmdb, "search", nothing)
    monkeypatch.setattr(main_module.igdb, "search", nothing)


def test_a_book_exports_with_its_isbn_and_no_screen_ids(client, seed):
    seed(source="openlibrary", source_id="OL59863W", title="The Dispossessed", year=1974,
         kind="book", isbn="9780061054884", status="queued", queue_position=10,
         why="Le Guin, finally")
    row = next(csv.DictReader(io.StringIO(client.get("/api/export.csv").text)))
    assert row["isbn"] == "9780061054884"
    assert row["kind"] == "book"
    assert row["tmdb_id"] == "" and row["igdb_id"] == "" and row["imdb_id"] == ""


def test_a_book_survives_export_and_import_as_the_same_work(
    client, seed, openlibrary_api, quiet_screen_sources,
):
    """AC8's round trip. The ISBN is spent as an id, so what comes back is the same WORK —
    not whatever happened to rank highest for the title."""
    seed(source="openlibrary", source_id="OL59863W", title="The Dispossessed", year=1974,
         kind="book", isbn="9780061054884", status="seen", stars=5,
         review="Earns it.", watched_at="2026-09-02T21:30:00+00:00")
    exported = client.get("/api/export.csv").text
    assert "9780061054884" in exported

    # Empty the list, then put the export back through the front door.
    from backend.db import connection
    with connection() as conn:
        conn.execute("DELETE FROM titles")

    preview = client.post("/api/import/preview", json={"text": exported})
    body = preview_result(preview)
    assert body["problems"] == []
    entry = body["rows"][0]
    assert entry["state"] == "matched", entry
    assert entry["chosen"]["source"] == "openlibrary"
    assert entry["chosen"]["source_id"] == "OL59863W", "the ISBN did not resolve to the work"

    committed = client.post("/api/import/commit", json={"entries": body["rows"]})
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["added"] == 1

    restored = client.get("/api/titles").json()[0]
    assert restored["source_id"] == "OL59863W"
    assert restored["kind"] == "book"
    assert restored["isbn"] == "9780061054884"


def test_an_isbn_row_is_resolved_without_any_title_search(
    client, seed, openlibrary_api, monkeypatch,
):
    """An ISBN is an id and is spent like one, BEFORE searching — the same reason a
    `tmdb_id` short-circuits the search."""
    import backend.main as main_module
    searched = []

    async def watched(query: str) -> list[dict]:
        searched.append(query)
        return []

    monkeypatch.setattr(main_module.tmdb, "search", watched)
    monkeypatch.setattr(main_module.igdb, "search", watched)
    monkeypatch.setattr(main_module.openlibrary, "search", watched)

    text = ("title,year,kind,isbn\n"
            "Something Mistyped Entirely,1974,book,9780061054884\n")
    body = preview_result(client.post("/api/import/preview", json={"text": text}))
    assert body["rows"][0]["state"] == "matched"
    assert body["rows"][0]["chosen"]["source_id"] == "OL59863W"
    assert searched == [], f"the ISBN row still ran a title search: {searched}"


def test_an_isbn_that_matches_nothing_falls_back_to_searching_by_title(
    client, openlibrary_api, quiet_screen_sources,
):
    """It must not become `unmatched` just because the ISBN was a typo — the title is
    still a perfectly good thing to search for, and the row says so."""
    text = "title,year,kind,isbn\nThe Dispossessed,1974,book,9999999999999\n"
    body = preview_result(client.post("/api/import/preview", json={"text": text}))
    entry = body["rows"][0]
    assert entry["state"] in ("matched", "choose")
    assert "ISBN" in entry.get("note", "")
    assert entry["chosen"]["source_id"] == "OL59863W"


# ── AC8: a row that says `book` must not match a film ────────────────────────────────────


def test_a_row_declaring_book_never_matches_a_same_titled_film(
    client, openlibrary_api, monkeypatch,
):
    """T-10's rule: a declared kind is a FILTER, not a preference. There is a 1974 novel
    and (for this test) a same-titled film; if the row says `book`, the film is not an
    answer to it."""
    import backend.main as main_module

    async def a_film(query: str) -> list[dict]:
        return [{
            "source": "tmdb", "source_id": "999", "media_type": "movie",
            "title": "The Dispossessed", "original_title": None, "year": 1974,
            "kind": "movie", "summary": None, "poster_url": None,
            "backdrop_url": None, "popularity": 9999.0,
        }]

    async def nothing(query: str) -> list[dict]:
        return []

    monkeypatch.setattr(main_module.tmdb, "search", a_film)
    monkeypatch.setattr(main_module.igdb, "search", nothing)

    text = "title,year,kind\nThe Dispossessed,1974,book\n"
    body = preview_result(client.post("/api/import/preview", json={"text": text}))
    entry = body["rows"][0]

    assert entry["candidates"], "the book row came back with no candidates at all"
    assert {c["kind"] for c in entry["candidates"]} == {"book"}
    assert all(c["source"] == "openlibrary" for c in entry["candidates"])
    assert entry["chosen"]["source_id"] == "OL59863W", (
        "the far more 'popular' film outranked the book the row actually asked for"
    )


def test_book_is_an_accepted_kind_in_the_csv_contract():
    assert "book" in csvio.KINDS


def test_an_unknown_kind_is_still_rejected():
    """Guard the guard: `KINDS` widening must not have turned into "anything goes"."""
    rows, problems = csvio.parse("title,kind\nA Thing,podcast\n")
    assert rows[0]["kind"] is None
    assert "unknown kind" in problems[0]


# ── AC6: an export taken BEFORE this ticket still imports after it ───────────────────────


@pytest.fixture
def offline_fetch(monkeypatch):
    """`main._fetch` for rows whose source is not the point of the test.

    The preview phase resolves a row carrying an id without any network at all; the COMMIT
    phase then fetches the full record for each one. These rows are TMDB and IGDB titles,
    which is not what the pre-T-16 fixture is here to prove."""
    import backend.main as main_module

    async def fetch(source: str, source_id: str, media_type: str | None = None) -> dict:
        return {
            "source": source, "source_id": str(source_id),
            "media_type": media_type or ("movie" if source == "tmdb" else "game"),
            "title": f"Restored {source_id}", "original_title": None, "year": 2000,
            "kind": "movie" if source == "tmdb" else "game", "summary": None,
            "poster_path": None, "backdrop_path": None, "genres": [], "detail": {},
            "imdb_id": None, "anilist_id": None,
        }

    monkeypatch.setattr(main_module, "_fetch", fetch)


def test_a_pre_t16_export_still_imports_cleanly(client, repo_root, offline_fetch, quiet_screen_sources):
    """The fixture was generated by `csvio.export_rows` at 154a54a, the commit before T-16 —
    thirteen columns, no `isbn`. Adding a column to a published contract must not break the
    files people already have, and `parse` reads by header NAME rather than by position,
    which is what makes that true."""
    fixture = repo_root / "tests" / "fixtures" / "pre-t16-export.csv"
    text = fixture.read_text(encoding="utf-8")
    assert "isbn" not in text.splitlines()[0], "the fixture is no longer a PRE-T-16 export"

    body = preview_result(client.post("/api/import/preview", json={"text": text}))
    assert body["problems"] == [], body["problems"]
    assert len(body["rows"]) == 6
    # Every row carried a tmdb_id or an igdb_id, so every row resolves exactly, as it did
    # before this ticket — no row silently became `unmatched` because a column appeared.
    assert {r["state"] for r in body["rows"]} == {"matched"}

    committed = client.post("/api/import/commit", json={"entries": body["rows"]})
    assert committed.status_code == 200, committed.text
    assert committed.json()["counts"]["added"] == 6

    restored = client.get("/api/titles").json()
    assert len(restored) == 6
    assert all(r["isbn"] is None for r in restored), "an isbn was invented for a pre-T-16 row"


def test_the_pre_t16_fixture_is_the_old_contract_exactly(repo_root):
    """If this fixture is ever regenerated by current code it stops testing anything."""
    header = (repo_root / "tests" / "fixtures" / "pre-t16-export.csv").read_text(
        encoding="utf-8").splitlines()[0]
    assert header.split(",") == [c for c in csvio.COLUMNS if c != "isbn"]
