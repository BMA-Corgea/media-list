"""AC2 — titles CRUD, star validation, and the rating transition (T-9's evidence, frozen).

Star bounds per `backend/main.py::update_title`: `1 <= stars <= 5`, whole numbers, bool
excluded explicitly (`isinstance(True, int)` is True in Python, so it needs its own check).
NOTE: `.autodev/plans/T-13.md` describes this as "0-5 integers accepted" — that is wrong
against both the code and T-9's own evidence table (`0 -> 400`); the tests below follow the
code and the evidence, not the plan text. See the T-13 handoff for detail.
"""

from __future__ import annotations

import pytest


def test_add_title_requires_source_and_source_id(client):
    resp = client.post("/api/titles", json={})
    assert resp.status_code == 400


def test_add_title_stores_a_fetched_record(client, fake_source):
    fake_source("tmdb", "603", title="The Matrix", kind="movie", year=1999)
    resp = client.post("/api/titles", json={"source": "tmdb", "source_id": "603", "why": "  a classic  "})
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "The Matrix"
    assert body["status"] == "queued"
    assert body["why"] == "a classic"  # stripped


def test_add_title_empty_why_stores_null_not_empty_string(client, fake_source):
    fake_source("tmdb", "1", title="A", kind="movie")
    resp = client.post("/api/titles", json={"source": "tmdb", "source_id": "1", "why": "   "})
    assert resp.status_code == 201
    assert resp.json()["why"] is None


def test_add_title_duplicate_is_409(client, fake_source):
    fake_source("tmdb", "1", title="A", kind="movie")
    first = client.post("/api/titles", json={"source": "tmdb", "source_id": "1"})
    assert first.status_code == 201
    second = client.post("/api/titles", json={"source": "tmdb", "source_id": "1"})
    assert second.status_code == 409
    assert "existing_id" in second.json()["detail"]


def test_get_title_404_for_unknown_id(client):
    resp = client.get("/api/titles/999999")
    assert resp.status_code == 404


def test_list_titles_default_and_status_filter(client, seed):
    seed(source="tmdb", source_id="1", title="Queued One", status="queued", queue_position=10)
    seed(source="tmdb", source_id="2", title="Seen One", status="seen", stars=5, watched_at="2026-01-01T00:00:00+00:00")

    everything = client.get("/api/titles").json()
    assert {t["title"] for t in everything} == {"Queued One", "Seen One"}

    queued_only = client.get("/api/titles", params={"status": "queued"}).json()
    assert [t["title"] for t in queued_only] == ["Queued One"]

    seen_only = client.get("/api/titles", params={"status": "seen"}).json()
    assert [t["title"] for t in seen_only] == ["Seen One"]


@pytest.mark.parametrize("stars", [1, 2, 3, 4, 5])
def test_valid_star_ratings_accepted(client, seed, stars):
    title_id = seed(source="tmdb", source_id=str(stars), title="T", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"stars": stars, "status": "seen"})
    assert resp.status_code == 200
    assert resp.json()["stars"] == stars


@pytest.mark.parametrize("bad_stars", [0, 6, -1, "4", 3.5, True])
def test_invalid_star_ratings_rejected(client, seed, bad_stars):
    title_id = seed(source="tmdb", source_id="x", title="T", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"stars": bad_stars})
    assert resp.status_code == 400


def test_marking_seen_without_stars_is_rejected(client, seed):
    title_id = seed(source="tmdb", source_id="1", title="T", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"status": "seen"})
    assert resp.status_code == 400


def test_rating_moves_title_out_of_the_queue(client, seed):
    title_id = seed(source="tmdb", source_id="1", title="T", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"stars": 4, "status": "seen"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "seen"
    assert body["queue_position"] is None
    assert body["watched_at"] is not None

    # Gone from the queued listing, present in seen.
    assert client.get("/api/titles", params={"status": "queued"}).json() == []
    seen = client.get("/api/titles", params={"status": "seen"}).json()
    assert [t["title"] for t in seen] == ["T"]


def test_unwatching_returns_to_end_of_queue_and_keeps_the_opinion(client, seed):
    seed(source="tmdb", source_id="1", title="Ahead", status="queued", queue_position=120)
    title_id = seed(
        source="tmdb", source_id="2", title="Rewatch Candidate", status="seen",
        stars=5, review="loved it", watched_at="2026-01-01T00:00:00+00:00",
    )

    resp = client.patch(f"/api/titles/{title_id}", json={"status": "queued"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["watched_at"] is None
    assert body["queue_position"] == 130  # MAX(120) + 10, not a stale/restored position
    # Opinion intact -- un-watching must not erase what was thought the first time.
    assert body["stars"] == 5
    assert body["review"] == "loved it"


def test_why_update_empty_string_stores_null(client, seed):
    title_id = seed(source="tmdb", source_id="1", title="T", why="original reason", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"why": "   "})
    assert resp.status_code == 200
    assert resp.json()["why"] is None


def test_patch_is_sparse_unrelated_fields_untouched(client, seed):
    title_id = seed(source="tmdb", source_id="1", title="T", why="keep me", status="queued", queue_position=10)
    resp = client.patch(f"/api/titles/{title_id}", json={"review": "just watched"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["review"] == "just watched"
    assert body["why"] == "keep me"  # untouched by a payload that never mentioned it


def test_remove_title(client, seed):
    title_id = seed(source="tmdb", source_id="1", title="T", status="queued", queue_position=10)
    resp = client.delete(f"/api/titles/{title_id}")
    assert resp.status_code == 200
    assert client.get(f"/api/titles/{title_id}").status_code == 404


def test_remove_unknown_title_is_404(client):
    resp = client.delete("/api/titles/999999")
    assert resp.status_code == 404
