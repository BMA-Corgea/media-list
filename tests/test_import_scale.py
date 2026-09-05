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

    calls = {"tmdb": 0, "igdb": 0, "queries": []}

    async def tmdb_search(query: str) -> list[dict]:
        calls["tmdb"] += 1
        calls["queries"].append(("tmdb", query))
        await _sleep(SEARCH_LATENCY)
        return [{
            "source": "tmdb", "source_id": f"gen-{query}", "media_type": "movie",
            "title": query, "original_title": None, "year": None, "kind": "movie",
            "summary": None, "poster_url": None, "backdrop_url": None, "popularity": 1.0,
        }]

    async def igdb_search(query: str) -> list[dict]:
        calls["igdb"] += 1
        calls["queries"].append(("igdb", query))
        await _sleep(SEARCH_LATENCY)
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
