"""Shared helpers for building fake source data, offline.

`backend.main._fetch(source, source_id, media_type)` is the one seam every endpoint that
needs a source record goes through (`add_title`, `import_commit`, `details`). Patching it
here — rather than faking HTTP responses shaped like TMDB/IGDB JSON — keeps these tests
about THIS app's behaviour (queue arithmetic, atomicity, validation) instead of coupling
them to upstream response shapes that have nothing to do with what T-13 is freezing.

`no_network` (conftest.py) still guards the real thing: if some code path bypasses `_fetch`
and reaches `client()` directly, that hits the raising MockTransport, not the internet.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable

import httpx
import pytest


@pytest.fixture
def fake_source(monkeypatch) -> Callable[..., dict]:
    """Registers canned records; patches `backend.main._fetch` to serve them.

    Usage: `fake_source("tmdb", "603", title="The Matrix", kind="movie", year=1999)`
    then POST `{"source": "tmdb", "source_id": "603"}` to `/api/titles`.
    """
    import backend.main as main_module

    records: dict[tuple[str, str], dict] = {}

    async def fetch(source: str, source_id: str, media_type: str | None = None) -> dict:
        key = (source, str(source_id))
        if key not in records:
            raise KeyError(f"fake_source: no record registered for {key} — call fake_source(...) first")
        return dict(records[key])

    monkeypatch.setattr(main_module, "_fetch", fetch)

    def register(source: str, source_id: str, **fields) -> dict:
        record = {
            "source": source,
            "source_id": str(source_id),
            "media_type": fields.pop("media_type", "movie" if source == "tmdb" else "game"),
            "title": "Fake Title",
            "original_title": None,
            "year": 2020,
            "kind": "movie" if source == "tmdb" else "game",
            "summary": None,
            "poster_url": None,
            "backdrop_url": None,
            "genres": [],
            "detail": {},
            "imdb_id": None,
            "anilist_id": None,
            "poster_path": None,
            "backdrop_path": None,
        }
        record.update(fields)
        records[(source, str(source_id))] = record
        return record

    return register


def preview_result(response) -> dict:
    """The final `/api/import/preview` payload, parsed out of its NDJSON progress stream.

    One place decides how a preview response is read, so the scale tests and the round-trip
    tests do not each have to know. T-15 gave the endpoint a progress channel (AC3): it now
    answers with a stream of newline-delimited events whose LAST line is the complete result,
    in the same shape the endpoint used to return in one blob.

    A test that cares about the progress itself reads the stream directly with
    `client.stream(...)` — see `tests/test_import_scale.py`. Everything else wants the answer.
    """
    import json as _json

    events = [_json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events, "the preview stream was empty — not even a `start` event"
    final = events[-1]
    assert final.get("event") != "error", f"the preview ended in an error event: {final!r}"
    assert final.get("event") == "result", (
        f"the preview stream did not end with a result event; last line was {final!r}. "
        "A truncated stream means the resolver died part-way."
    )
    return final


# ── the seam BELOW the rate limiter (T-15 round 2, F5) ────────────────────────────────────
#
# `fake_source` and the scale tests' `scale_sources` both patch ABOVE `RateLimit`: they
# replace `_fetch` or `tmdb.search`/`igdb.search` outright, so nothing they measure has ever
# been near the limiter. That is the right seam for "does this app's orchestration work", and
# it is the wrong seam for "how long will the owner actually wait" — which is set entirely by
# the per-source ceilings the limiter enforces.
#
# `UpstreamTransport` is the other seam: a real `httpx` transport, so a call reaches it only
# by going through `client()`, `*_LIMIT.slot()` and the source module's own parsing. It
# records a timestamp per departure, which is what makes an honest requests-per-second
# measurement possible.


class UpstreamTransport(httpx.AsyncBaseTransport):
    """Answers TMDB / IGDB / Twitch with a simulated round trip, and times every departure.

    Deliberately NOT `httpx.MockTransport`: that calls a synchronous handler, so a whole
    "request" can complete without ever yielding to the event loop. Nothing would interleave,
    concurrency would be invisible, and a test of concurrent behaviour would pass by never
    being concurrent. `await asyncio.sleep(latency)` here is what makes these calls behave
    like calls that leave the machine.
    """

    def __init__(self, latency: float = 0.05, games: bool = False) -> None:
        self.latency = latency
        self.games = games
        self.departures: list[tuple[float, str, str]] = []  # (monotonic, host, path)
        self.started = time.monotonic()
        self.in_flight = 0
        self.peak = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.departures.append((time.monotonic(), request.url.host, request.url.path))
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.latency)
            return self._answer(request)
        finally:
            self.in_flight -= 1

    def _answer(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        if host == "api.themoviedb.org":
            query = dict(request.url.params).get("query", "Untitled")
            return httpx.Response(200, json={"results": [{
                "id": abs(hash(query)) % 100000, "media_type": "movie", "title": query,
                "original_title": query, "release_date": "2001-01-01", "overview": "",
                "poster_path": None, "backdrop_path": None, "popularity": 1.0,
                "genre_ids": [], "original_language": "en",
            }]})
        if host == "openlibrary.org":
            # `_search_all` consults every source per title and Open Library is always on,
            # so every scale run now passes through here. Answering with no docs keeps these
            # tests measuring what they were written to measure (pacing and concurrency of
            # the paid-for sources) while still costing a real round trip.
            return httpx.Response(200, json={"numFound": 0, "docs": []})
        if host == "api.igdb.com":
            if not self.games:
                return httpx.Response(200, json=[])
            body = request.content.decode()
            name = body.split('"')[1] if '"' in body else "Untitled"
            return httpx.Response(200, json=[{
                "id": abs(hash(name)) % 100000, "name": name, "summary": "",
                "first_release_date": 978307200, "total_rating_count": 1,
            }])
        raise AssertionError(f"UpstreamTransport got an unexpected host: {request.url}")

    # ── what the departures mean ──────────────────────────────────────────────────────────

    def count(self, host: str) -> int:
        return sum(1 for _, h, _ in self.departures if h == host)

    def rate(self, host: str) -> float:
        """Observed requests per second for one host, over its own first-to-last window.

        Measured across the window the requests actually occupy, not across the whole test,
        so an unrelated slow phase before or after cannot flatter the number.
        """
        stamps = [at for at, h, _ in self.departures if h == host]
        if len(stamps) < 2:
            return 0.0
        return (len(stamps) - 1) / (stamps[-1] - stamps[0])


@pytest.fixture
def upstream(monkeypatch) -> Callable[..., UpstreamTransport]:
    """Point every source module's `client` at an `UpstreamTransport`, and hand it back.

    Patched per MODULE, not on `base`, for the reason `conftest.py::no_network` spells out:
    `tmdb.py`/`igdb.py`/`anilist.py` each did `from .base import client`, which binds a name
    in the importing module. This replaces `no_network`'s blocking client for the duration of
    the test, and only for the modules named.
    """
    from backend import artwork
    from backend.sources import anilist, base, igdb, openlibrary, tmdb

    def install(latency: float = 0.05, games: bool = False) -> UpstreamTransport:
        transport = UpstreamTransport(latency=latency, games=games)

        def stubbed_client(*_args, **_kwargs) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=transport)

        for module in (base, tmdb, igdb, anilist, openlibrary, artwork):
            monkeypatch.setattr(module, "client", stubbed_client)
        return transport

    return install


@pytest.fixture
def cold_igdb_token(monkeypatch, tmp_path) -> None:
    """An IGDB token cache that is empty, private to this test, and never the real one.

    `igdb.TOKEN_CACHE` is resolved from `config.data_dir` at import. Under the test config
    that is already a throwaway directory, but it is SHARED for the whole session — so one
    test writing a token would silently give the next test a warm cache and quietly delete
    the cold-start behaviour it was trying to measure.
    """
    from backend.sources import igdb

    monkeypatch.setattr(igdb, "TOKEN_CACHE", tmp_path / "igdb-token.json")
