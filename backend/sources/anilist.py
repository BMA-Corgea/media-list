"""AniList — the anime specifics TMDB is thin on.

No key, no account. There is also no id mapping from TMDB, so this matches on title, which
means matches are FUZZY and occasionally wrong.

Because of that this module DECORATES and never REPLACES: it may add a studio, an episode
count, a season, or the romaji/English title pair. It may not touch `title`, `year` or
`kind`, because a wrong fuzzy match would then rename a title the user already recognised.
"""

from __future__ import annotations

from .base import client

ENDPOINT = "https://graphql.anilist.co"

QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    episodes
    season
    seasonYear
    format
    studios(isMain: true) { nodes { name } }
    title { romaji english }
  }
}
"""


async def enrich(title: str) -> dict:
    """Extras for an anime, or an empty dict.

    Never raises. AniList is a nice-to-have on top of a TMDB record that is already complete;
    a failure here must not fail the request that carries it.
    """
    try:
        async with client() as http:
            response = await http.post(ENDPOINT, json={"query": QUERY, "variables": {"search": title}})
            if not response.is_success:
                return {}
            media = (response.json().get("data") or {}).get("Media")
    except Exception:
        return {}

    if not media:
        return {}

    studios = [n["name"] for n in (media.get("studios") or {}).get("nodes", [])]
    names = media.get("title") or {}
    extras = {
        "anilist_id": media.get("id"),
        "episodes": media.get("episodes"),
        "season": f"{media['season'].title()} {media['seasonYear']}"
        if media.get("season") and media.get("seasonYear")
        else None,
        "format": media.get("format"),
        "studio": studios[0] if studios else None,
        "title_romaji": names.get("romaji"),
        "title_english": names.get("english"),
    }
    return {k: v for k, v in extras.items() if v is not None}
