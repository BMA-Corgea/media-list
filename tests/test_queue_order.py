"""AC2 — queue arithmetic (T-7's evidence, frozen): gap-tolerant append/prepend, midpoint
insert, gap exhaustion forcing a renumber to multiples of 10, and reordering by neighbour
IDS surviving a filtered view untouched.

The defect T-7 actually found (see `.autodev/evidence/T-7/build.md`): trusting BOTH caller
neighbours let four different inserts between positions 5 and 10 all compute the same
midpoint 7. The fix reads one bound from the database as whatever is genuinely adjacent right
now; `test_move_after_only_the_named_bound_is_trusted` below is the regression test for that
exact defect.
"""

from __future__ import annotations


def positions(client) -> dict[str, int]:
    rows = client.get("/api/titles", params={"status": "queued"}).json()
    return {r["title"]: r["queue_position"] for r in rows}


def test_append_lands_at_max_plus_ten(client, seed, fake_source):
    seed(source="tmdb", source_id="1", title="First", status="queued", queue_position=30)
    fake_source("tmdb", "2", title="Second", kind="movie")
    resp = client.post("/api/titles", json={"source": "tmdb", "source_id": "2"})
    assert resp.status_code == 201
    assert resp.json()["queue_position"] == 40


def test_append_on_an_empty_queue_starts_at_ten(client, fake_source):
    fake_source("tmdb", "1", title="Only", kind="movie")
    resp = client.post("/api/titles", json={"source": "tmdb", "source_id": "1"})
    assert resp.json()["queue_position"] == 10


def test_move_to_top_lands_at_min_minus_ten(client, seed):
    seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=10)
    b_id = seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=20)

    resp = client.patch(f"/api/titles/{b_id}", json={"move_to_top": True})
    assert resp.status_code == 200
    assert resp.json()["queue_position"] == 0  # MIN(10) - 10


def test_move_after_named_neighbour_lands_between_it_and_its_real_successor(client, seed):
    a_id = seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=10)
    seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=20)
    c_id = seed(source="tmdb", source_id="3", title="C", status="queued", queue_position=30)

    resp = client.post(f"/api/titles/{c_id}/move", json={"after_id": a_id})
    assert resp.status_code == 200
    pos = positions(client)
    assert pos["A"] < pos["C"] < pos["B"]


def test_move_before_named_neighbour_lands_between_its_real_predecessor_and_it(client, seed):
    a_id = seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=10)
    seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=20)
    c_id = seed(source="tmdb", source_id="3", title="C", status="queued", queue_position=30)

    resp = client.post(f"/api/titles/{c_id}/move", json={"before_id": a_id})
    assert resp.status_code == 200
    pos = positions(client)
    assert pos["C"] < pos["A"] < pos["B"]


def test_move_with_neither_bound_sends_it_to_the_end(client, seed):
    a_id = seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=10)
    b_id = seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=20)

    resp = client.post(f"/api/titles/{a_id}/move", json={})
    assert resp.status_code == 200
    pos = positions(client)
    assert pos["B"] < pos["A"]


def test_move_after_only_the_named_bound_is_trusted_not_a_caller_supplied_pair(client, seed):
    """The exact defect from T-7's build evidence: four inserts "between 5 and 10" all
    computing midpoint 7 because both bounds came from the caller. The far bound must be
    read from the database — whichever row is genuinely adjacent right now — not trusted
    from the request. Two separate inserts after the same row must land in the CORRECT
    relative order, not collide."""
    a_id = seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=5)
    seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=10)

    first = seed(source="tmdb", source_id="3", title="First", status="queued", queue_position=200)
    client.post(f"/api/titles/{first}/move", json={"after_id": a_id})

    second = seed(source="tmdb", source_id="4", title="Second", status="queued", queue_position=201)
    client.post(f"/api/titles/{second}/move", json={"after_id": a_id})

    pos = positions(client)
    # Second was inserted after A more recently, so it must be the one directly after A;
    # First must have been pushed along, still ahead of B. All four positions unique.
    assert pos["A"] < pos["Second"] < pos["First"] < pos["B"]
    assert len(set(pos.values())) == 4


def test_gap_exhaustion_forces_a_renumber_to_multiples_of_ten(client, seed):
    """A=1, B=2 (adjacent integers, no room between them) — inserting C "after A" cannot
    find an integer in (1, 2), so the queue must renumber (to multiples of SPREAD=10) before
    it can place C, and C must still land immediately after A once it does."""
    a_id = seed(source="tmdb", source_id="1", title="A", status="queued", queue_position=1)
    seed(source="tmdb", source_id="2", title="B", status="queued", queue_position=2)
    c_id = seed(source="tmdb", source_id="3", title="C", status="queued", queue_position=100)

    resp = client.post(f"/api/titles/{c_id}/move", json={"after_id": a_id})
    assert resp.status_code == 200

    pos = positions(client)
    assert pos["A"] < pos["C"] < pos["B"]
    assert len(set(pos.values())) == 3
    # Hand-verified two-step arithmetic: `_renumber` first respreads ALL THREE rows in
    # their current order (A=1,B=2,C=100 -> A=10,B=20,C=30, SPREAD=10 from `main.py`), since
    # C already exists in the table at that point even though it is the row being moved.
    # Bounds are then recomputed against those fresh positions and ONLY THEN is C placed at
    # the midpoint of its real gap (10, 20) -> 15, overwriting the 30 the renumber gave it.
    assert pos["A"] == 10
    assert pos["B"] == 20
    assert pos["C"] == 15


def test_reordering_inside_one_kind_leaves_every_other_kind_relative_order_untouched(client, seed):
    """T-7 AC5, replayed: drag a game to the front of the games "inside the games filter" —
    which, server-side, is just "move by id" — and every non-game title must keep its exact
    relative order. There is no server-side kind filter; id-addressed moves make this safe
    by construction rather than by a correction pass."""
    g1 = seed(source="tmdb", source_id="g1", title="G1", kind="game", status="queued", queue_position=10)
    seed(source="tmdb", source_id="m1", title="M1", kind="movie", status="queued", queue_position=20)
    seed(source="tmdb", source_id="a1", title="A1", kind="anime", status="queued", queue_position=30)
    seed(source="tmdb", source_id="g2", title="G2", kind="game", status="queued", queue_position=40)
    seed(source="tmdb", source_id="m2", title="M2", kind="movie", status="queued", queue_position=50)
    seed(source="tmdb", source_id="a2", title="A2", kind="anime", status="queued", queue_position=60)
    g3 = seed(source="tmdb", source_id="g3", title="G3", kind="game", status="queued", queue_position=70)

    before = client.get("/api/titles", params={"status": "queued"}).json()
    non_game_order_before = [t["title"] for t in before if t["kind"] != "game"]

    resp = client.post(f"/api/titles/{g3}/move", json={"before_id": g1})
    assert resp.status_code == 200

    after = client.get("/api/titles", params={"status": "queued"}).json()
    non_game_order_after = [t["title"] for t in after if t["kind"] != "game"]
    game_order_after = [t["title"] for t in after if t["kind"] == "game"]

    assert non_game_order_after == non_game_order_before == ["M1", "A1", "M2", "A2"]
    assert game_order_after == ["G3", "G1", "G2"]
