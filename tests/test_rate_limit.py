"""T-15 AC6 — the outbound rate is bounded, documented, and actually wired in.

Two separate things have to be true and each has its own failure mode:

  * the limiter WORKS — it paces departures and caps open requests;
  * the limiter is REACHED — every source's HTTP call goes through it.

The second is the one that rots quietly. A new call site added next to an old one, without
a slot around it, leaves the ceiling looking enforced while requests walk straight past it,
so the "is it wired" cases below patch each source module's OWN `*_LIMIT` name (never
`base`'s) — `from .base import TMDB_LIMIT` binds a name in the importing module and patching
the definition site does nothing to it. That is `kb/wiki/lessons.md`'s own lesson, applied.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.sources import anilist, base, igdb, tmdb
from backend.sources.base import ANILIST_LIMIT, IGDB_LIMIT, TMDB_LIMIT, RateLimit


class RecordingLimit:
    """Stands in for a RateLimit and records that a slot was taken."""

    def __init__(self) -> None:
        self.taken = 0

    def slot(self):
        outer = self

        class _Slot:
            async def __aenter__(self):
                outer.taken += 1

            async def __aexit__(self, *_exc):
                return False

        return _Slot()


# ── the numbers themselves ────────────────────────────────────────────────────────────────
# These are the published ceilings, copied from each upstream's own documentation into
# `base.py`'s comments. Pinning them here means "the ceiling is written down, not implicit"
# (AC6) cannot quietly become a different number than the one the comment explains.


def test_the_published_ceilings_are_what_base_documents():
    assert (IGDB_LIMIT.per_second, IGDB_LIMIT.open_requests) == (4, 8)
    assert (TMDB_LIMIT.per_second, TMDB_LIMIT.open_requests) == (20, 8)
    assert (ANILIST_LIMIT.per_second, ANILIST_LIMIT.open_requests) == (1.5, 4)


def test_igdb_is_the_strictest_upstream_and_therefore_sets_the_shape():
    """The reason `SEARCH_CONCURRENCY` is 8 and not larger lives in this comparison."""
    from backend.main import SEARCH_CONCURRENCY

    assert IGDB_LIMIT.per_second == min(
        IGDB_LIMIT.per_second, TMDB_LIMIT.per_second
    ), "TMDB is now the tighter limit — SEARCH_CONCURRENCY's stated reasoning is stale"
    assert SEARCH_CONCURRENCY <= min(IGDB_LIMIT.open_requests, TMDB_LIMIT.open_requests), (
        "the import fetch phase may start more requests at once than an upstream says it "
        "will hold open"
    )


# ── the limiter works ─────────────────────────────────────────────────────────────────────


def test_slot_paces_departures_at_the_declared_rate(run_async):
    limit = RateLimit("test", per_second=50, open_requests=8)  # 20ms apart

    async def one() -> None:
        async with limit.slot():
            return None

    async def five() -> float:
        started = time.monotonic()
        await asyncio.gather(*(one() for _ in range(5)))
        return time.monotonic() - started

    elapsed = run_async(five())
    # Five departures 20ms apart is 80ms of spacing after the first. Anything materially
    # under that means requests are leaving in a burst.
    assert elapsed >= 0.075, f"five paced calls finished in {elapsed:.3f}s — no pacing happened"


def test_slot_caps_how_many_requests_are_open_at_once(run_async):
    limit = RateLimit("test", per_second=1000, open_requests=3)
    peak = {"now": 0, "max": 0}

    async def one():
        async with limit.slot():
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            await asyncio.sleep(0.01)
            peak["now"] -= 1

    async def twenty():
        await asyncio.gather(*(one() for _ in range(20)))

    run_async(twenty())
    assert peak["max"] <= 3, f"{peak['max']} requests were open at once against a cap of 3"
    assert peak["max"] > 1, "nothing ran concurrently — the cap is being applied as a lock"


def test_a_limiter_survives_being_used_from_a_second_event_loop(run_async):
    """The gotcha `_bind` exists for.

    `asyncio.Lock`/`Semaphore` bind to the first loop that touches them and raise on any
    other. These limiters are module-scope singletons and the app gets a fresh loop per run
    (and per `TestClient` in this suite), so a limiter built once at import would work in the
    first test and raise ``bound to a different event loop`` in the second.
    """
    limit = RateLimit("test", per_second=1000, open_requests=2)

    async def once():
        async with limit.slot():
            return "ok"

    assert run_async(once()) == "ok"
    assert run_async(once()) == "ok"  # a different loop entirely — this is the assertion


# ── the limiter is reached ────────────────────────────────────────────────────────────────


def test_tmdb_search_takes_a_slot_before_the_request_leaves(monkeypatch, no_network, run_async):
    recorder = RecordingLimit()
    monkeypatch.setattr(tmdb, "TMDB_LIMIT", recorder)
    monkeypatch.setattr(tmdb, "available", lambda: True)

    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(tmdb.search("Cowboy Bebop"))
    assert recorder.taken == 1, "tmdb.search reached the network without taking a slot"
    assert len(no_network) == 1


def test_tmdb_details_takes_a_slot_before_the_request_leaves(monkeypatch, no_network, run_async):
    recorder = RecordingLimit()
    monkeypatch.setattr(tmdb, "TMDB_LIMIT", recorder)
    monkeypatch.setattr(tmdb, "available", lambda: True)

    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(tmdb.details("603", "movie"))
    assert recorder.taken == 1


def test_igdb_token_and_query_both_take_a_slot(monkeypatch, no_network, run_async):
    recorder = RecordingLimit()
    monkeypatch.setattr(igdb, "IGDB_LIMIT", recorder)
    monkeypatch.setattr(igdb, "available", lambda: True)

    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(igdb.search("Hollow Knight"))
    # The Twitch token exchange is an outbound request like any other and is paced too — it
    # is the first thing a cold import does, once per run.
    assert recorder.taken == 1


def test_anilist_enrich_takes_a_slot(monkeypatch, no_network, run_async):
    recorder = RecordingLimit()
    monkeypatch.setattr(anilist, "ANILIST_LIMIT", recorder)

    # enrich() swallows everything and returns {} by design, so the slot count is the proof.
    assert run_async(anilist.enrich("Cowboy Bebop")) == {}
    assert recorder.taken == 1


def test_every_source_module_that_calls_client_also_imported_a_limit():
    """The guard against a fifth source module appearing with no ceiling at all.

    Mirrors `conftest.py::_NETWORK_MODULES`, which has the same shape of list for the same
    reason: a module that reaches `client()` and is missing from one of these two lists is
    invisible to both the network guard and the rate ceiling.
    """
    import inspect

    for module in (tmdb, igdb, anilist):
        source = inspect.getsource(module)
        assert "client()" in source
        assert "_LIMIT.slot()" in source, (
            f"{module.__name__} makes outbound calls but never takes a rate-limit slot — "
            "add one, and add its ceiling to backend/sources/base.py with the upstream's "
            "published number (T-15 AC6)."
        )
    # `base` defines the limits; it must not itself be making requests.
    assert "await http" not in inspect.getsource(base)


# ── the token exchange, which concurrency made a cold-start problem (T-15 round 2, F4) ────


def test_a_cold_start_exchanges_exactly_one_twitch_token(upstream, cold_igdb_token, run_async):
    """A T-15 REGRESSION, introduced by the thing T-15 exists to do.

    `token()` caches a bearer token on disk and reuses it. That was enough while resolution
    was SEQUENTIAL: exactly one row could be inside `token()` at a time, so exactly one
    exchange could ever be in flight and the second row found the cache warm.

    Concurrency broke it. `SEARCH_CONCURRENCY` rows now start together, all eight miss the
    same cold cache, and all eight POST to Twitch — measured at 8 exchanges in 3.75s where 1
    is correct. Each one also takes an `IGDB_LIMIT` slot, so a cold import spends its first
    two seconds of IGDB budget on seven token exchanges nobody needed, at the exact moment
    the first eight rows are trying to search.

    The limiter is left at its real published rate here on purpose: 4/s is what makes seven
    redundant exchanges cost real time rather than nothing.
    """
    transport = upstream(latency=0.01)

    async def eight_rows_at_once() -> None:
        await asyncio.gather(*(igdb.search(f"Game {n}") for n in range(8)))

    started = time.monotonic()
    run_async(eight_rows_at_once())
    elapsed = time.monotonic() - started

    exchanges = transport.count("id.twitch.tv")
    assert exchanges == 1, (
        f"{exchanges} Twitch token exchanges for one cold import — eight rows starting "
        f"together each missed the cache and each authenticated ({elapsed:.2f}s). One row "
        "should exchange and the other seven should wait for it (T-15 F4)."
    )
    assert transport.count("api.igdb.com") == 8, "the searches themselves did not all happen"


def test_a_warm_token_is_not_re_exchanged(upstream, cold_igdb_token, monkeypatch, run_async):
    """The lock must not have turned the cache into a per-call exchange.

    A second batch, on an already-warm cache, must add NO exchanges at all — the fast path
    has to stay outside the lock, or every IGDB call in the process serialises behind it.

    Paced loosely here (this is about COUNTS, not wall clock) so the suite does not spend two
    seconds proving something arithmetic. The real rate is measured in the test above.
    """
    monkeypatch.setattr(igdb, "IGDB_LIMIT", RateLimit("igdb", per_second=1000, open_requests=8))
    transport = upstream(latency=0.005)

    async def four(label: str) -> None:
        await asyncio.gather(*(igdb.search(f"{label} {n}") for n in range(4)))

    run_async(four("First"))
    after_first = transport.count("id.twitch.tv")
    run_async(four("Second"))

    assert after_first == 1
    assert transport.count("id.twitch.tv") == 1, (
        "a warm cache still exchanged another token — `token()`'s fast path is not being "
        "taken any more."
    )


def test_the_token_lock_does_not_serialise_the_searches_behind_it(
    upstream, cold_igdb_token, monkeypatch, run_async
):
    """The lock guards the EXCHANGE, not the searches.

    A lock held across the whole of `token()` — or worse, across `_query` — would quietly
    turn IGDB into a one-request-at-a-time source and undo the fetch phase T-15 exists for.
    Measured at the transport, which is below every limiter: more than one IGDB request has
    to be genuinely open at once.

    The rate ceiling is relaxed for this one, because at the real 4/s the pacing alone would
    keep requests one at a time and the assertion could not tell a lock from a limit.
    """
    monkeypatch.setattr(igdb, "IGDB_LIMIT", RateLimit("igdb", per_second=1000, open_requests=8))
    transport = upstream(latency=0.05)

    async def eight() -> None:
        await asyncio.gather(*(igdb.search(f"Overlap {n}") for n in range(8)))

    run_async(eight())

    assert transport.count("id.twitch.tv") == 1
    assert transport.peak > 1, (
        "never more than one request open at a time — the token lock is being held across "
        "the searches, not just across the exchange."
    )
