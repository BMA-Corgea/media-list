"""Shared plumbing for the metadata sources.

Three small clients are less code than three SDK dependencies, and there is no maintained
Python SDK for IGDB anyway. What they do share lives here.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

#: Generous, but bounded. The owner deprioritised speed on repo-tour; search here is typed into,
#: so a hung upstream must fail rather than hang the box someone is typing in.
TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)


class SourceError(Exception):
    """An upstream failed, and we say WHICH one and why.

    The failure mode this exists to prevent is a source dying silently and the user reading
    an empty result list as "there are no matches" — which is a lie the UI would tell on the
    API's behalf.
    """

    def __init__(self, source: str, detail: str, status: int | None = None) -> None:
        self.source = source
        self.detail = detail
        self.status = status
        super().__init__(f"{source}: {detail}")

    def as_dict(self) -> dict:
        return {"source": self.source, "error": self.detail, "status": self.status}


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)


def raise_for(source: str, response: httpx.Response) -> None:
    """Turn an upstream HTTP failure into something a human can act on."""
    if response.is_success:
        return
    if response.status_code == 401:
        raise SourceError(source, "credentials rejected — check the key in .env", 401)
    if response.status_code == 429:
        raise SourceError(source, "rate limited — try again shortly", 429)
    raise SourceError(source, f"HTTP {response.status_code}", response.status_code)


# ── the outbound ceiling (T-15 AC6) ────────────────────────────────────────────────────────
#
# WHY THIS IS CORRECTNESS AND NOT POLITENESS.
# `raise_for` above turns HTTP 429 into a SourceError, and `main.import_preview` catches that
# PER ROW and marks the row `unmatched`. So going over an upstream's limit does not fail
# loudly — it silently degrades a thousand-row import into a thousand rows that "have no
# match", on the owner's real list, with no sign anything went wrong. The rate below is what
# stops that cascade of false negatives.
#
# A concurrency cap alone is NOT a rate. Eight requests in flight at 200ms each is 40
# requests/second — ten times IGDB's published limit. Both ceilings are needed, so `RateLimit`
# carries both.


class RateLimit:
    """Bounds how FAST, and how MANY AT ONCE, requests leave for one upstream.

    `slot()` is an async context manager wrapped around the actual HTTP call, so every path
    that reaches a source is paced — search, details, and the import fetch phase alike. Callers
    do not opt in per feature; there is one door and it is here.
    """

    def __init__(self, source: str, per_second: float, open_requests: int) -> None:
        self.source = source
        self.per_second = per_second
        self.open_requests = open_requests
        self.interval = 1.0 / per_second
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._gate: asyncio.Semaphore | None = None
        self._next = 0.0

    def _bind(self) -> tuple[asyncio.Lock, asyncio.Semaphore]:
        """Build (or rebuild) the primitives for whatever loop is running now.

        GOTCHA this exists for: `asyncio.Lock` and `asyncio.Semaphore` bind themselves to the
        first running loop that touches them and raise ``… is bound to a different event
        loop`` on any other one. These limiters live at module scope for the life of the
        process, but the app gets a fresh event loop per run — and a fresh one per
        `TestClient` in the suite — so constructing them once at import would work in the
        first test and blow up in the second. Rebuilt on a loop change instead; the pacing
        clock resets with them, which is correct, because a new loop means no requests of
        ours are in flight.
        """
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._lock = asyncio.Lock()
            self._gate = asyncio.Semaphore(self.open_requests)
            self._next = 0.0
        return self._lock, self._gate  # type: ignore[return-value]

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Wait until this request is allowed to leave, then hold an open-request slot."""
        lock, gate = self._bind()
        async with gate:
            # Reserve a departure time under the lock, then sleep OUTSIDE it: holding the
            # lock across the sleep would serialise the whole source down to one request at a
            # time regardless of `open_requests`.
            async with lock:
                now = time.monotonic()
                start = max(now, self._next)
                self._next = start + self.interval
            delay = start - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            yield


#: IGDB publishes BOTH of these: 4 requests/second and a maximum of 8 open requests. It is the
#: strictest upstream this app talks to and therefore the one that sets the shape of the whole
#: import. A thousand game rows genuinely takes minutes against it; that is an upstream fact,
#: not something local concurrency can or should route around.
IGDB_LIMIT = RateLimit("igdb", per_second=4, open_requests=8)

#: TMDB dropped its hard 40-per-10-seconds cap in 2020 and now publishes guidance of roughly
#: 50 requests/second. 20 is a deliberate margin: this app has no retry-with-backoff, so it
#: should sit well under a limit it cannot recover from crossing.
TMDB_LIMIT = RateLimit("tmdb", per_second=20, open_requests=8)

#: AniList allows 90 requests/minute (1.5/s) and has been observed dropping to 30/minute during
#: incidents. `anilist.enrich` runs once per title STORED, never once per row previewed, so
#: this is generous for the only path that uses it.
ANILIST_LIMIT = RateLimit("anilist", per_second=1.5, open_requests=4)

#: Open Library publishes no hard number for `search.json`, only a request to be gentle — and
#: an UNAUTHENTICATED source has no key for them to throttle, so the only thing standing
#: between a thousand-row book import and an IP block is this line. 5/s is deliberately
#: conservative: below TMDB's 20 because there is no published allowance to sit under, above
#: AniList's 1.5 because a book import consults this source once PER ROW rather than once per
#: title stored, and `details` costs two requests rather than one.
#:
#: Their covers API does document 100 requests per 5 minutes — but only for covers addressed
#: by ISBN or OLID. `openlibrary.cover_url` addresses them by cover ID, which is the
#: unthrottled form, and artwork is fetched through `artwork.cache` anyway (see the note at
#: the bottom of this file about why that path is bounded elsewhere).
OPENLIBRARY_LIMIT = RateLimit("openlibrary", per_second=5, open_requests=4)

# Artwork is deliberately NOT paced here. `artwork.cache` fetches from image.tmdb.org,
# images.igdb.com and covers.openlibrary.org — CDNs with no published request limit for the
# by-id form this app uses — and it is already bounded to `main.SEARCH_CONCURRENCY`
# downloads at a time because it only ever runs inside `main._fetch`.
