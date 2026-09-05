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

import asyncio
import json
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


# ── AC3: the preview does not block until the last row ────────────────────────────────────


def _stream(client, csv_text: str) -> list[dict]:
    """Every event the endpoint sent, in order.

    NOT USABLE FOR TIMING, and that is a property of the test client, not of the server.
    `starlette.testclient.TestClient` runs the app through a portal and collects the WHOLE
    response body into a `BytesIO` before `iter_lines()` yields its first line — see
    `_TestClientTransport.handle_request`, which ends with
    `raw_kwargs["stream"] = httpx.ByteStream(raw_kwargs["stream"].read())`. So every event
    appears to arrive at the same instant no matter what the server actually did, and a
    timing assertion made here would be measuring httpx's buffer.

    Same shape of trap as T-13's path-traversal lesson: the in-process client is the one
    thing that cannot reproduce the property under test. The timing proof therefore drives
    the generator directly, below; this helper is for ORDER and CONTENT, which it can see.
    """
    seen: list[dict] = []
    with client.stream("POST", "/api/import/preview", json={"text": csv_text}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        for line in response.iter_lines():
            if line.strip():
                seen.append(json.loads(line))
    return seen


def test_progress_is_emitted_while_the_resolver_is_still_working(run_async, scale_sources):
    """AC3 — proven at the layer that does the work, with a real clock on each yield.

    See `_stream` for why this cannot be measured through `TestClient`. `_preview_events` is
    the async generator the endpoint hands to `StreamingResponse`, so timestamping its yields
    measures exactly what a browser reading the socket would see, with nothing in between.
    """
    from backend import csvio
    from backend.main import _PreviewRun, _preview_events

    rows, problems = csvio.parse(generate_csv(ROWS))
    assert len(rows) == ROWS

    async def drain() -> list[tuple[float, dict]]:
        started = time.perf_counter()
        seen: list[tuple[float, dict]] = []
        # `_PreviewRun` starts a task, so it can only be built with a loop already running —
        # which is also how the endpoint builds it.
        async for line in _preview_events(_PreviewRun(rows, problems, set())):
            seen.append((time.perf_counter() - started, json.loads(line)))
        return seen

    seen = run_async(drain())
    events = [event for _, event in seen]

    assert events[0]["event"] == "start"
    assert events[0]["total"] == ROWS
    assert events[-1]["event"] == "result"
    assert len(events[-1]["rows"]) == ROWS

    progress = [(at, event) for at, event in seen if event["event"] == "progress"]
    assert progress, "no progress events at all — the preview still blocks until the end"

    finished_at = seen[-1][0]
    first_progress_at = progress[0][0]
    assert first_progress_at < finished_at / 2, (
        f"the first progress event was emitted {first_progress_at:.3f}s in, out of "
        f"{finished_at:.3f}s total — that is not progress, that is the answer arriving late."
    )
    # Enough of them that a browser sees a number that moves, not two updates and a wait.
    assert len(progress) >= 10, f"only {len(progress)} progress events over {ROWS} rows"

    # It counts up, it never goes backwards, and it lands exactly on the total.
    counts = [event["resolved"] for _, event in progress]
    assert counts == sorted(counts)
    assert counts[-1] == ROWS
    assert all(event["total"] == ROWS for _, event in progress)


def test_the_last_line_of_the_stream_is_the_whole_answer(client, scale_sources):
    """The FINAL LINE alone is exactly what this endpoint used to return, in the same shape.

    Not the same as saying the change was additive, which an earlier docstring did say: the
    content type moved to `application/x-ndjson` and the body as a whole is no longer valid
    JSON. A client still has to split on newlines and parse the last line. What this pins is
    the narrower and true claim — the shape of that last line did not move.
    """
    result = _stream(client, repeated_csv(40, 10))[-1]

    assert set(result) == {"event", "rows", "problems", "counts", "existing"}
    assert result["counts"] == {"matched": 40}
    assert all(set(row) >= {"row", "state", "chosen", "candidates"} for row in result["rows"])


def test_an_empty_file_still_answers_in_the_stream_s_own_shape(client):
    """The no-rows path went through the same door — a client should not need two parsers."""
    seen = _stream(client, "")
    assert [event["event"] for event in seen] == ["start", "result"]
    assert seen[-1]["rows"] == []
    assert seen[-1]["problems"] == ["the file is empty"]


def test_a_failure_part_way_through_becomes_a_terminal_error_event(client, monkeypatch):
    """Once the first byte is out, a 500 is no longer available. This is what replaces it.

    Without the terminal event a stream that simply stopped would parse as a successful
    preview of however many rows happened to make it — a half-resolved list presented as a
    whole one, which is the failure mode T-10's whole design exists to avoid.
    """
    import backend.main as main_module

    async def exploding_search(query: str) -> list[dict]:
        raise ValueError("upstream client blew up in a way SourceError does not cover")

    monkeypatch.setattr(main_module.tmdb, "search", exploding_search)
    monkeypatch.setattr(main_module.igdb, "search", exploding_search)

    final = _stream(client, generate_csv(5))[-1]
    assert final["event"] == "error", f"expected a terminal error event, got {final!r}"
    assert "nothing was written" in final["detail"]


# ── walking away: proven against the shape the real server actually takes ─────────────────
#
# THE DEFECT THIS SECTION EXISTS BECAUSE OF (T-15 round 2, F1).
# The first version of this test closed the stream with `await events.aclose()` and passed
# against code that could not survive a real disconnect. `aclose()` throws into the generator
# frame, so the generator's `finally` runs — and the generator's `finally` was the fix. The
# test and the fix agreed with each other about a path production does not take.
#
# Starlette cancels `stream_response` when the client goes (`StreamingResponse.__call__` races
# it against `listen_for_disconnect` in an anyio task group). WHERE that cancellation lands is
# the whole question:
#
#   in-anext   cancelled while awaiting the generator  -> thrown in, `finally` runs
#   in-send    cancelled while awaiting `send(chunk)`   -> generator left suspended at its
#                                                          yield, `finally` NEVER runs
#
# in-send is the one production hits, because uvicorn awaits `flow.drain()` whenever the write
# buffer is paused — the state a thousand-row preview with a closing client is in. So both
# shapes are driven here, through the REAL `StreamingResponse.__call__`, over the REAL ASGI
# three-tuple, against the object the real endpoint returns. Nothing calls `aclose()`.

#: Leave after the start line and a couple of progress lines — far enough in that plenty of
#: rows are still unresolved, early enough that the run is nowhere near finished.
CHUNKS_BEFORE_LEAVING = 3


async def _client_leaves(response, *, inside_send: bool) -> None:
    """Drive a real ASGI response with a client that disconnects mid-stream.

    `inside_send=True` is the production shape: `send` never returns, the way uvicorn's
    `flow.drain()` does not return while the write buffer is paused, so the disconnect is
    delivered to `stream_response` while it is suspended in `send` and the generator is left
    parked at its `yield`.

    `inside_send=False` is the other branch: `send` returns immediately, `stream_response`
    goes back to the generator, and the cancellation is thrown into the generator frame.
    """
    left = asyncio.Event()
    chunks = {"n": 0}

    async def receive() -> dict:
        await left.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] != "http.response.body" or not message.get("body"):
            return
        chunks["n"] += 1
        if chunks["n"] < CHUNKS_BEFORE_LEAVING:
            return
        left.set()
        if inside_send:
            await asyncio.Event().wait()  # a write that will never complete

    await response({"type": "http"}, receive, send)


@pytest.mark.parametrize("inside_send", [False, True], ids=["in-anext", "in-send"])
def test_walking_away_from_a_preview_stops_the_searches(run_async, scale_sources, inside_send):
    """The half of AC3's design that is a claim about quota, not about the UI.

    Streaming was chosen over a polled job id partly because an abandoned preview should stop
    spending TMDB/IGDB requests rather than finish a thousand-row run for nobody. That is not
    free — see `backend/main.py::_PreviewRun` — so it is measured, on both cancellation shapes.

    Before the fix this was red on `in-send` and green on `in-anext`: 600 rows, disconnect
    after 40 searches, and 1072 more searches went out to the upstreams for a client that had
    already gone.
    """
    import backend.main as main_module
    from backend.main import SEARCH_CONCURRENCY

    async def walk_away() -> tuple[int, int, bool]:
        response = await main_module.import_preview(payload={"text": generate_csv(600)})
        await _client_leaves(response, inside_send=inside_send)

        at_close = scale_sources["tmdb"] + scale_sources["igdb"]
        # `ag_frame` is None once a generator has finished or been closed. On the in-send
        # shape it is still a frame, which is the point: the searches stopped WITHOUT the
        # generator's `finally` ever running. Holding this reference is also what keeps the
        # garbage collector from finalising it behind the test's back.
        suspended = getattr(response.body_iterator, "ag_frame", None) is not None
        # Far longer than the whole preview takes when it is allowed to run.
        await asyncio.sleep(0.3)
        return at_close, scale_sources["tmdb"] + scale_sources["igdb"], suspended

    at_close, later, suspended = run_async(walk_away())

    assert at_close < 600 * 2, "the whole preview had already run before the client left"
    assert later - at_close <= SEARCH_CONCURRENCY, (
        f"{later - at_close} more searches went out after the client walked away — an "
        "abandoned preview is still spending upstream quota. Cancellation is hanging off "
        "something that only runs when the generator frame is resumed (T-15 F1)."
    )
    if inside_send:
        assert suspended, (
            "the generator was finalised after all, so this run did not reproduce the "
            "in-send shape and proves nothing about it — check `_client_leaves`."
        )
