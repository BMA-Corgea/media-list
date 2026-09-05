"""AC6 — no network by default, proven positively rather than assumed.

Each test below calls a real source function with `available()` forced True (so the code
does not bail out early for lack of credentials — the guard has to actually intercept the
outbound call, not merely benefit from a missing key). If any of these ever reached the
real internet, `no_network`'s handler is what stops it; these tests are here so a change
that quietly breaks that patching (e.g. a fifth module importing `client` and not being
added to `_NETWORK_MODULES`) fails LOUDLY here instead of leaking a live call from some
unrelated test months later.
"""

from __future__ import annotations

import pytest

from backend.sources import anilist, igdb, tmdb


def test_tmdb_search_is_blocked(monkeypatch, no_network, run_async):
    monkeypatch.setattr(tmdb, "available", lambda: True)
    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(tmdb.search("Cowboy Bebop"))
    assert len(no_network) == 1
    assert "api.themoviedb.org" in no_network[0]


def test_tmdb_details_is_blocked(monkeypatch, no_network, run_async):
    monkeypatch.setattr(tmdb, "available", lambda: True)
    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(tmdb.details("123", "movie"))
    assert len(no_network) == 1


def test_igdb_search_is_blocked(monkeypatch, no_network, run_async):
    monkeypatch.setattr(igdb, "available", lambda: True)
    with pytest.raises(RuntimeError, match="blocked outbound request"):
        run_async(igdb.search("Hollow Knight"))
    # search -> token() (no cached token) -> _query(): two distinct outbound attempts,
    # both blocked. Either count above zero proves the guard; asserting >= 1 keeps this
    # from being brittle against that internal detail changing.
    assert len(no_network) >= 1
    assert all("igdb.com" in a or "twitch.tv" in a for a in no_network)


def test_anilist_enrich_is_blocked_but_never_raises(no_network, run_async):
    """anilist.enrich() is designed to swallow every exception and return {} — so the proof
    here is not `pytest.raises`, it's that the blocked handler was actually reached."""
    result = run_async(anilist.enrich("Cowboy Bebop"))
    assert result == {}
    assert len(no_network) == 1
    assert "graphql.anilist.co" in no_network[0]


def test_artwork_cache_is_blocked_but_never_raises(no_network, run_async):
    """artwork.cache() also swallows exceptions and returns None on failure."""
    from backend import artwork

    result = run_async(artwork.cache("https://image.tmdb.org/t/p/w500/does-not-matter.jpg"))
    assert result is None
    assert len(no_network) == 1


def test_no_network_fixture_actually_patches_base_client():
    """The default (non-live) case: `base.client` is the fixture's `blocked_client`, not the
    real one — checked by qualname so this needs no network call to prove either way."""
    from backend.sources import base

    assert base.client.__qualname__ != "client"
    assert "blocked_client" in base.client.__qualname__


@pytest.mark.live
def test_live_marker_bypasses_the_guard():
    """A `live`-marked test gets the REAL `client` back, not the mock — proof the marker
    check in `no_network` actually works. Runs only with `--live`; needs no credentials."""
    from backend.sources import base

    assert base.client.__qualname__ == "client"
