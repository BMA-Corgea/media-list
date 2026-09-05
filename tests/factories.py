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
