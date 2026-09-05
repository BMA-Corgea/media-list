"""T-15 — the resolver at the scale the owner will actually use it.

The owner has no list yet and intends to generate one by chatting with a chatbot, then
importing it in one go (`kb/notes/handoff.md` §7 item 6). So the FIRST real use of the
importer is also its first load test, on data he cares about. Everything here is the
measurement that turns "untested past ~7 rows" (§7 item 5) into a number that can fail.

WHY THE STUB SLEEPS
-------------------
A stub that returns instantly measures nothing: the whole defect is that the resolver awaits
network round trips ONE AT A TIME, and a zero-latency stub makes a sequential loop and a
concurrent one look identical. So `scale_sources` awaits `SEARCH_LATENCY` per call — a
scaled-down stand-in for a real round trip — and the ceiling below is a bound on how much of
that latency the resolver is unable to overlap.

WHAT THE CEILING IS AND IS NOT
------------------------------
It is a bound on THIS code's orchestration overhead at a simulated latency. It is NOT a
prediction of real-world wall clock: against live TMDB/IGDB the wall clock is dominated by
the documented per-source rate limits (see `backend/sources/base.py::RateLimit`), which no
amount of local concurrency can or should get around.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import pytest

from tests.factories import preview_result

#: A chatbot list of this size is exactly what the README's own prompt invites; the spec asks
#: for >= 1000 (AC1).
ROWS = 1000

#: Stand-in for one upstream round trip. Real TMDB is ~200ms; 2ms keeps a 2000-call run inside
#: a test suite while preserving the only property that matters here — that time spent waiting
#: on a source is time that CAN be overlapped and, before T-15, was not.
SEARCH_LATENCY = 0.002

#: THE DOCUMENTED CEILING (AC2). `ROWS` rows x 2 sources x SEARCH_LATENCY = 4.0s of simulated
#: upstream latency. Sequential resolution cannot beat that number and MEASURED 4.95s; the
#: ceiling is set below it so this test is RED against the sequential resolver and stays red
#: if concurrency is ever removed. It is deliberately several times the post-fix measurement
#: (~0.75s) rather than hugging it, because a wall-clock assertion on a shared CI box must
#: fail on a structural regression, not on a noisy neighbour.
CEILING_SECONDS = 2.0


def generate_csv(rows: int) -> str:
    """`rows` DISTINCT titles in the README's starter format.

    Distinct on purpose: this file's ceiling test must measure concurrency, not the cache.
    Repeated titles get their own test (`test_import_cache.py` territory / AC5) so a green
    number here can only mean one thing.
    """
    lines = ["title,year,kind,why"]
    for index in range(rows):
        lines.append(f"Generated Title {index:04d},{1980 + index % 40},movie,row {index}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def scale_sources(monkeypatch) -> dict:
    """`tmdb.search`/`igdb.search` replaced with latency-simulating stubs; returns a counter.

    Patched at the SEARCH function, not at the HTTP layer, for two reasons. It keeps the run
    honest about what is being measured (this app's orchestration, not httpx), and it keeps
    `conftest.py::no_network`'s positive guard fully in force underneath — if any of this ever
    reached `client()` it would still raise.
    """
    import backend.main as main_module

    calls = {"tmdb": 0, "igdb": 0, "queries": [], "in_flight": 0, "peak": 0}

    @asynccontextmanager
    async def counted(source: str, query: str):
        calls[source] += 1
        calls["queries"].append((source, query))
        calls["in_flight"] += 1
        calls["peak"] = max(calls["peak"], calls["in_flight"])
        try:
            await _sleep(SEARCH_LATENCY)
            yield
        finally:
            calls["in_flight"] -= 1

    async def tmdb_search(query: str) -> list[dict]:
        async with counted("tmdb", query):
            return [{
                "source": "tmdb", "source_id": f"gen-{query}", "media_type": "movie",
                "title": query, "original_title": None, "year": None, "kind": "movie",
                "summary": None, "poster_url": None, "backdrop_url": None, "popularity": 1.0,
            }]

    async def igdb_search(query: str) -> list[dict]:
        async with counted("igdb", query):
            return []

    monkeypatch.setattr(main_module.tmdb, "search", tmdb_search)
    monkeypatch.setattr(main_module.igdb, "search", igdb_search)
    return calls


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


def test_a_thousand_row_preview_resolves_every_row(client, scale_sources):
    """AC1 — >= 1000 rows drive the resolver end to end, and nothing is dropped."""
    resp = client.post("/api/import/preview", json={"text": generate_csv(ROWS)})
    assert resp.status_code == 200
    body = preview_result(resp)

    assert body["problems"] == []
    assert len(body["rows"]) == ROWS
    # Every row gets a verdict. "Nothing is dropped in silence" is T-10's whole premise and
    # it has to survive at 1000 rows, not just at 7.
    assert body["counts"] == {"matched": ROWS}
    assert scale_sources["tmdb"] == ROWS
    assert scale_sources["igdb"] == ROWS


def test_a_thousand_row_preview_stays_under_the_documented_ceiling(client, scale_sources):
    """AC2 — the bound is enforced, not felt.

    RED before T-15's fix: the resolver awaits 2000 round trips strictly one after another,
    so it cannot finish in less than ROWS x 2 x SEARCH_LATENCY = 4.0s no matter how fast the
    machine is. That is the before-value.
    """
    csv_text = generate_csv(ROWS)

    started = time.perf_counter()
    resp = client.post("/api/import/preview", json={"text": csv_text})
    elapsed = time.perf_counter() - started

    assert resp.status_code == 200
    assert len(preview_result(resp)["rows"]) == ROWS

    simulated = ROWS * 2 * SEARCH_LATENCY
    assert elapsed <= CEILING_SECONDS, (
        f"a {ROWS}-row preview took {elapsed:.2f}s against a documented ceiling of "
        f"{CEILING_SECONDS:.2f}s. {simulated:.2f}s of that is simulated upstream latency that "
        "the resolver is supposed to overlap — a number at or above it means the fetch phase "
        "went back to awaiting one row at a time (T-15 AC2)."
    )


# ── AC5: the cache, and what concurrency must not have cost ───────────────────────────────


def repeated_csv(rows: int, distinct: int) -> str:
    """`rows` rows drawn from only `distinct` titles — a franchise list, roughly.

    "Gundam", "Gundam Wing", "Gundam SEED" is the shape the locate calls out: a chatbot list
    repeats itself, and before T-15 every repeat paid full price for the same two round trips.
    """
    lines = ["title,year,kind,why"]
    for index in range(rows):
        title = f"Repeated Title {index % distinct:03d}"
        lines.append(f"{title},2001,movie,row {index}")
    return "\n".join(lines) + "\n"


def test_identical_lookups_hit_the_cache_instead_of_the_network_twice(client, scale_sources):
    """AC5 — 1000 rows over 50 distinct titles cost 50 searches per source, not 1000."""
    resp = client.post("/api/import/preview", json={"text": repeated_csv(ROWS, 50)})
    assert resp.status_code == 200
    body = preview_result(resp)

    assert len(body["rows"]) == ROWS
    assert body["counts"] == {"matched": ROWS}
    assert scale_sources["tmdb"] == 50, (
        f"{scale_sources['tmdb']} TMDB searches for 50 distinct titles — the per-run cache "
        "is not collapsing identical lookups (T-15 AC5)."
    )
    assert scale_sources["igdb"] == 50
    # Not one title was searched twice, even though 20 rows wanted each of them at once. The
    # cache stores the in-flight task, so rows that start together share one round trip.
    assert len(set(scale_sources["queries"])) == len(scale_sources["queries"])


def test_rows_differing_only_in_the_year_share_one_search_and_still_rank_separately(
    client, scale_sources
):
    """The cache key is the title alone — which is the entire input to a search call.

    `year` is applied afterwards, per row, when ranking. So two rows claiming different years
    for the same title are one search and two independent verdicts, not one shared verdict.
    """
    csv_text = (
        "title,year,kind,why\n"
        "Cowboy Bebop,1998,movie,the anime\n"
        "Cowboy Bebop,2021,movie,the live-action one\n"
        "  cowboy   bebop ,1998,movie,whitespace and case are not a different title\n"
    )
    body = preview_result(client.post("/api/import/preview", json={"text": csv_text}))

    assert scale_sources["tmdb"] == 1, "three rows naming one title made more than one search"
    assert len(body["rows"]) == 3
    assert [r["row"]["year"] for r in body["rows"]] == [1998, 2021, 1998]


def test_the_number_of_searches_in_flight_never_exceeds_the_documented_bound(
    client, scale_sources
):
    """AC6 — the bound is a real ceiling on outbound requests, not a hopeful constant."""
    from backend.main import SEARCH_CONCURRENCY

    client.post("/api/import/preview", json={"text": generate_csv(ROWS)})

    assert scale_sources["peak"] <= SEARCH_CONCURRENCY, (
        f"{scale_sources['peak']} searches were in flight at once against a documented bound "
        f"of {SEARCH_CONCURRENCY} (T-15 AC6)."
    )
    assert scale_sources["peak"] > 1, (
        "nothing overlapped at all — the fetch phase is back to one row at a time, and the "
        "ceiling test above is passing for the wrong reason."
    )


# ── AC8: T-10's guarantees still hold at 1000 rows, not just at 7 ─────────────────────────
#
# These are T-10 AC8-AC10 replayed at scale. They are here rather than in
# `test_csv_roundtrip.py` because what is under test is not the CSV contract — it is whether
# a concurrent fetch phase feeding a sequential insert loop still produces the same answers
# the seven-row version did.


def _entry(source_id: str, title: str, kind: str = "movie", **row) -> dict:
    fields = {
        "title": title, "year": 2020, "kind": kind, "why": None, "status": None,
        "stars": None, "queue_position": None, "tmdb_id": None, "igdb_id": None,
        "imdb_id": None, "added_at": None, "watched_at": None, "review": None,
    }
    fields.update(row)
    return {
        "row": fields,
        "chosen": {"source": "tmdb", "source_id": source_id, "media_type": "movie",
                   "title": title, "year": fields["year"], "kind": kind},
    }


def test_a_thousand_rows_carrying_tmdb_ids_make_no_searches_at_all(client, scale_sources):
    """T-10 AC8 at scale — an id is trusted, so an export round-trips without touching TMDB."""
    lines = ["title,year,kind,tmdb_id"]
    for index in range(ROWS):
        lines.append(f"Exported Title {index:04d},2005,movie,{5000 + index}")
    body = preview_result(client.post("/api/import/preview", json={"text": "\n".join(lines) + "\n"}))

    assert len(body["rows"]) == ROWS
    assert body["counts"] == {"matched": ROWS}
    assert scale_sources["tmdb"] == 0 and scale_sources["igdb"] == 0, (
        "rows carrying a tmdb_id caused a search — the id fast path is what makes an export "
        "round-trip EXACT rather than approximate (T-10 AC8)."
    )


def test_at_scale_titles_already_on_the_list_are_reported_not_re_added(client, seed, fake_source):
    """T-10 AC9 at scale — 200 of a 500-row batch already exist and stay exactly one row each."""
    for index in range(200):
        seed(source="tmdb", source_id=f"big-{index}", title=f"Big Title {index}",
             status="queued", queue_position=(index + 1) * 10)

    entries = []
    for index in range(500):
        fake_source("tmdb", f"big-{index}", title=f"Big Title {index}", kind="movie", year=2020)
        entries.append(_entry(f"big-{index}", f"Big Title {index}"))

    result = client.post("/api/import/commit", json={"entries": entries}).json()
    assert result["counts"] == {"added": 300, "skipped": 200, "failed": 0}
    assert all("already on the list" in s["reason"] for s in result["skipped"])
    assert len(client.get("/api/titles").json()) == 500


def test_at_scale_a_batch_appends_gap_tolerantly_in_file_order(client, seed, fake_source):
    """T-10 AC10 / T-7 at scale — MAX+10 per row, in the order the file listed them.

    This is the property that would break first if the INSERT loop were ever made concurrent:
    `top += 10` is order-dependent and has no parallel form. A shuffled or duplicated set of
    positions here means the queue arithmetic moved somewhere it does not belong.
    """
    seed(source="tmdb", source_id="anchor", title="Anchor", status="queued", queue_position=1000)

    entries = []
    for index in range(300):
        fake_source("tmdb", f"app-{index}", title=f"Appended {index:03d}", kind="movie", year=2020)
        entries.append(_entry(f"app-{index}", f"Appended {index:03d}"))

    assert client.post("/api/import/commit", json={"entries": entries}).json()["counts"]["added"] == 300

    queued = [t for t in client.get("/api/titles?status=queued").json() if t["title"] != "Anchor"]
    queued.sort(key=lambda t: t["queue_position"])
    assert [t["queue_position"] for t in queued] == [1010 + 10 * i for i in range(300)]
    # Positions ascend in FILE order, which is what `asyncio.gather` preserving its input
    # order buys: the fetches finished in whatever order they liked.
    assert [t["title"] for t in queued] == [f"Appended {i:03d}" for i in range(300)]


def test_at_scale_a_bulk_append_never_resurrects_a_seen_row(client, seed, fake_source):
    """T-10 AC10's second half — the Seen archive is not a place the importer can drag out of."""
    seed(source="tmdb", source_id="watched", title="Already Watched", status="seen",
         stars=5, review="loved it", queue_position=None, watched_at="2026-01-01T00:00:00+00:00")

    entries = []
    for index in range(400):
        fake_source("tmdb", f"bulk-{index}", title=f"Bulk {index:03d}", kind="movie", year=2020)
        entries.append(_entry(f"bulk-{index}", f"Bulk {index:03d}"))
    # The seen title is in the middle of the batch, where a sequential loop would reach it
    # long after it had already started writing.
    fake_source("tmdb", "watched", title="Already Watched", kind="movie", year=2020)
    entries.insert(200, _entry("watched", "Already Watched"))

    result = client.post("/api/import/commit", json={"entries": entries}).json()
    assert result["counts"] == {"added": 400, "skipped": 1, "failed": 0}

    watched = next(t for t in client.get("/api/titles").json() if t["title"] == "Already Watched")
    assert watched["status"] == "seen"
    assert watched["queue_position"] is None
    assert watched["stars"] == 5 and watched["review"] == "loved it"


def test_the_same_title_twice_in_one_batch_is_fetched_once_and_added_once(client, fake_source):
    """AC5's other half — concurrency creates no duplicate titles.

    The in-batch duplicate check is a `SELECT` on the transaction's OWN connection, so it sees
    the uncommitted insert made by the earlier copy. That only works while the insert loop is
    sequential and single-connection.
    """
    fake_source("tmdb", "twin", title="Seen Double", kind="movie", year=2020)
    entries = [_entry("twin", "Seen Double", why=f"copy {i}") for i in range(20)]

    result = client.post("/api/import/commit", json={"entries": entries}).json()
    assert result["counts"] == {"added": 1, "skipped": 19, "failed": 0}
    assert len(client.get("/api/titles").json()) == 1
