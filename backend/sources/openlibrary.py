"""Open Library — books.

THE SOURCE THAT NEEDS NO KEY, which is the one thing about it that is structurally new.
Every other source here gates on credentials: `tmdb.available()` reads an API key,
`igdb.available()` reads a client id and secret, and `/api/health` reports what is
configured. `available()` below is unconditionally True, because openlibrary.org answers
anonymously — verified live: `search.json` returned 603 results for "The Dispossessed", and
`covers.openlibrary.org` serves the artwork keyless too. Google Books was checked as an
alternative and returns HTTP 429 unauthenticated, so it is a fallback at best.

That makes "always on" a THIRD state for callers that were written to think in "configured
or not", and both places that ask are told the truth rather than a convenient lie — see
`main.health` and `main.search`.

NOT the AniList shape. `sources/anilist.py` says of itself that it DECORATES and never
REPLACES; it is absent from the schema's `source` CHECK for exactly that reason. Open
Library supplies title, year and kind on its own, so it is a first-class origin like tmdb
and igdb, and T-16 put it in that CHECK.

IDENTITY IS THE WORK, NOT THE EDITION. `source_id` is a work key (`OL59863W`), so the
seventy-five printings of The Dispossessed are ONE thing on the list — the same rule T-1
set for series, and what makes `(source, source_id)` still mean "already on your list".
"""

from __future__ import annotations

import re

from .base import OPENLIBRARY_LIMIT, SourceError, client, raise_for

BASE = "https://openlibrary.org"
COVER = "https://covers.openlibrary.org/b/id"

#: Asked for by name. `search.json` returns a large document per hit otherwise — and `isbn`
#: alone can be a hundred entries for a well-published work, which is why it is requested
#: only where it is wanted (details) and not on every keystroke (search).
SEARCH_FIELDS = "key,title,author_name,first_publish_year,cover_i,edition_count"
DETAIL_FIELDS = SEARCH_FIELDS + ",subject,isbn,number_of_pages_median"

#: How many subjects survive onto a title page. Open Library returns them by the dozen, in
#: several languages, ordered by nothing in particular; the whole list is noise on a card.
MAX_SUBJECTS = 8


def available() -> bool:
    """Always. There is no key to be missing, so there is no state where books are off.

    Deliberately still a function with the same name and shape as `tmdb.available` and
    `igdb.available`: callers ask every source the same question, and a source that had to
    be special-cased at each call site would be special-cased wrongly at one of them.
    """
    return True


def work_id(key: str) -> str:
    """`/works/OL59863W` -> `OL59863W`. Ids are stored bare and rebuilt into URLs here."""
    return (key or "").rsplit("/", 1)[-1]


def cover_url(cover_id, size: str = "L") -> str | None:
    """A cover URL from a cover ID.

    Covers addressed BY ID are the ones Open Library does not rate limit; the by-ISBN and
    by-OLID forms are the throttled ones. Search already hands us the id, so the cheap door
    is also the correct one.
    """
    return f"{COVER}/{cover_id}-{size}.jpg" if cover_id else None


def _author(doc: dict) -> str | None:
    names = doc.get("author_name") or []
    return names[0] if names else None


def _isbn(doc: dict) -> str | None:
    """One ISBN out of the hundred a popular work carries, chosen the same way every time.

    A work has many editions and therefore many ISBNs, none of which is "the" ISBN. The
    array's own order is not stable between calls, so picking `[0]` would make the value
    flap between imports of the same book. Preferring the numerically smallest ISBN-13 is
    arbitrary in the same way any choice would be, but it is DETERMINISTIC, which is the
    property the CSV round trip actually needs.
    """
    codes = [str(code).strip() for code in (doc.get("isbn") or []) if code]
    thirteens = sorted(c for c in codes if len(c) == 13 and c.isdigit())
    if thirteens:
        return thirteens[0]
    return sorted(codes)[0] if codes else None


def _normalise(doc: dict) -> dict | None:
    identifier = work_id(doc.get("key", ""))
    if not identifier or not doc.get("title"):
        return None
    return {
        "source": "openlibrary",
        "source_id": identifier,
        # Carried for symmetry with tmdb/igdb, which persist it so a title can be refreshed
        # later. Books have one namespace, so it is always this.
        "media_type": "book",
        "title": doc["title"],
        "original_title": None,
        "year": doc.get("first_publish_year"),
        "kind": "book",
        "summary": None,          # search.json carries no description; /details fetches it
        "poster_url": cover_url(doc.get("cover_i")),
        # Books have no landscape art at all. NULL by design, exactly as `imdb_id` is for a
        # game — the title page falls back rather than inventing something.
        "backdrop_url": None,
        # The nearest honest analogue of TMDB's popularity: how many times this work has
        # been published. It is the ranking signal `main.search` sorts on, and a work with
        # seventy-five editions genuinely is the one someone typing that title means.
        "popularity": doc.get("edition_count") or 0,
    }


async def _search(params: dict) -> list[dict]:
    async with client() as http:
        async with OPENLIBRARY_LIMIT.slot():
            response = await http.get(f"{BASE}/search.json", params=params)
        raise_for("openlibrary", response)
        return response.json().get("docs", [])


async def search(query: str) -> list[dict]:
    docs = await _search({"q": query, "fields": SEARCH_FIELDS, "limit": 12})
    return [n for n in (_normalise(doc) for doc in docs) if n]


async def by_isbn(isbn: str) -> dict | None:
    """The WORK an ISBN belongs to, or None. This is what makes a book round-trip exactly.

    `csvio` carries one id column per source so that an export re-imports as the same thing
    rather than being re-guessed by title — its own comment calls an id-less row the
    difference between an exact round trip and an approximate one. Books have no such id
    column: the owner asked for `isbn`, and only `isbn`. This is what makes that enough.

    An ISBN names one EDITION, and every edition belongs to exactly one work, so the
    lookup is exact rather than a search that happens to rank well — verified against live
    data: the ISBN-10 `0061054887` and the ISBN-13 `9780061054884` both resolve to
    `/works/OL59863W`, which is the id `details` would have stored. So the arbitrary edition
    whose ISBN got exported still leads back to the one work the list holds.
    """
    # ISBNs are written with hyphens and spaces by humans and by half the web; Open Library
    # indexes them bare. `X` is a legal ISBN-10 check digit, so it survives the strip.
    bare = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    if not bare:
        return None
    docs = await _search({"q": f"isbn:{bare}", "fields": SEARCH_FIELDS, "limit": 1})
    return _normalise(docs[0]) if docs else None


async def details(source_id: str) -> dict:
    """The full record for one work: author, subjects, an ISBN, and the description.

    Two requests, because no single Open Library endpoint carries all of it. `search.json`
    filtered to one work key is the only place author NAMES come back resolved — the works
    API gives author *keys* and would need a further request each to turn into names — and
    the works API is the only place the description lives.
    """
    identifier = work_id(source_id)
    if not identifier:
        raise SourceError("openlibrary", "a work id is required", 400)

    docs = await _search({"q": f"key:/works/{identifier}", "fields": DETAIL_FIELDS, "limit": 1})
    if not docs:
        raise SourceError("openlibrary", f"no work with id {identifier}", 404)

    doc = docs[0]
    record = _normalise(doc)
    if record is None:
        raise SourceError("openlibrary", f"work {identifier} came back unusable", 502)

    subjects = [str(s) for s in (doc.get("subject") or [])][:MAX_SUBJECTS]
    record.update({
        "genres": subjects,
        # Books have no IMDb entry, the same way games do not. Null by design; the title
        # page links to Open Library instead and the schema allows it.
        "imdb_id": None,
        "isbn": _isbn(doc),
        "summary": await _description(identifier),
        "detail": {
            "author": _author(doc),
            "pages": doc.get("number_of_pages_median"),
            "editions": doc.get("edition_count"),
            "openlibrary_url": f"{BASE}/works/{identifier}",
        },
    })
    return record


async def _description(identifier: str) -> str | None:
    """The work's blurb, or None.

    Returns None rather than raising: a book with no description is still worth adding, and
    this is the SECOND request of a details call whose first one already succeeded. Failing
    the whole add because the blurb 404'd would throw away a good record over a nice-to-have
    — the same judgement `artwork.cache` and `anilist.enrich` already make.
    """
    try:
        async with client() as http:
            async with OPENLIBRARY_LIMIT.slot():
                response = await http.get(f"{BASE}/works/{identifier}.json")
            if not response.is_success:
                return None
            description = response.json().get("description")
    except Exception:
        return None

    # Open Library returns this as either a bare string or {"type": ..., "value": ...},
    # depending on how old the record is. Both are current in live data.
    if isinstance(description, dict):
        description = description.get("value")
    description = (description or "").strip()
    return description or None
