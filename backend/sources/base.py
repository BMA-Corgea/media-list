"""Shared plumbing for the metadata sources.

Three small clients are less code than three SDK dependencies, and there is no maintained
Python SDK for IGDB anyway. What they do share lives here.
"""

from __future__ import annotations

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
