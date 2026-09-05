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

from typing import Callable

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
    """The final `/api/import/preview` payload, however that endpoint frames it.

    One place decides how a preview response is read, so the scale tests and the round-trip
    tests do not each have to know. Today that is a single JSON body; T-15 gives the endpoint
    a progress channel, and only this function has to learn about it.
    """
    return response.json()
