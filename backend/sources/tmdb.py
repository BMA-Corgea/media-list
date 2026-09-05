"""The Movie Database — films, television, and most anime.

TMDB is the spine for everything that is not a game. It is also the only free source of an
IMDb id: IMDb itself has no public API, and TMDB's `external_ids` is how the outbound links
in this app exist at all.
"""

from __future__ import annotations

from ..config import config
from .base import SourceError, client, raise_for

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"

#: TMDB's "Animation" genre. Necessary for anime, nowhere near sufficient — it is also every
#: Pixar film, which is why the language/origin test below is ANDed with it.
GENRE_ANIMATION = 16


def available() -> bool:
    return bool(config.tmdb_api_key)


def _image(path: str | None, size: str) -> str | None:
    """TMDB returns bare path fragments, not URLs. Nothing renders without this."""
    return f"{IMG}/{size}{path}" if path else None


def infer_kind(result: dict) -> str:
    """anime · movie · live-action, from what a search result actually carries.

    The two signals differ by media type — tv results carry `origin_country`, movie results
    carry `original_language` — so the Japanese test accepts either. Requiring both would
    miss every anime film; requiring neither would file Toy Story as anime.
    """
    media_type = result.get("media_type")
    genres = result.get("genre_ids") or []
    japanese = "JP" in (result.get("origin_country") or []) or result.get("original_language") == "ja"

    if GENRE_ANIMATION in genres and japanese:
        return "anime"
    if media_type == "tv":
        return "live-action"
    return "movie"


def _normalise(result: dict) -> dict | None:
    media_type = result.get("media_type")
    if media_type not in ("movie", "tv"):
        return None  # person results — not things you watch

    title = result.get("title") or result.get("name") or ""
    date = result.get("release_date") or result.get("first_air_date") or ""
    return {
        "source": "tmdb",
        "source_id": str(result["id"]),
        "media_type": media_type,
        "title": title,
        "original_title": result.get("original_title") or result.get("original_name"),
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "kind": infer_kind(result),
        "summary": result.get("overview") or None,
        "poster_url": _image(result.get("poster_path"), "w500"),
        "backdrop_url": _image(result.get("backdrop_path"), "w1280"),
        "popularity": result.get("popularity") or 0,
    }


async def search(query: str) -> list[dict]:
    if not available():
        raise SourceError("tmdb", "no TMDB_API_KEY in .env")
    async with client() as http:
        response = await http.get(
            f"{BASE}/search/multi",
            params={"api_key": config.tmdb_api_key, "query": query, "include_adult": "false"},
        )
        raise_for("tmdb", response)
        results = response.json().get("results", [])
    return [n for n in (_normalise(r) for r in results) if n]


async def details(source_id: str, media_type: str | None = None) -> dict:
    """Full record plus the IMDb id, which `search/multi` does not carry."""
    if not available():
        raise SourceError("tmdb", "no TMDB_API_KEY in .env")

    # TMDB's movie and tv ids are SEPARATE NAMESPACES: id 30991 is Cowboy Bebop as a tv id
    # and "The Curse of the Living Corpse" (1964) as a movie id. Guessing therefore does not
    # fail — it silently returns a different, entirely plausible title, with the wrong
    # poster and the wrong IMDb id. Storing that would quietly put the wrong film on the
    # list. So the caller must say which namespace it means; search results always carry it.
    if media_type not in ("movie", "tv"):
        raise SourceError(
            "tmdb",
            f"media_type is required (movie or tv) — id {source_id} means different titles "
            f"in each namespace and guessing returns the wrong one",
            400,
        )

    async with client() as http:
        for kind in [media_type]:
            response = await http.get(
                f"{BASE}/{kind}/{source_id}",
                params={"api_key": config.tmdb_api_key, "append_to_response": "external_ids"},
            )
            if response.status_code == 404:
                continue
            raise_for("tmdb", response)
            data = response.json()
            date = data.get("release_date") or data.get("first_air_date") or ""
            genres = [g["name"] for g in data.get("genres", [])]
            detail = {
                "runtime": data.get("runtime"),
                "episodes": data.get("number_of_episodes"),
                "seasons": data.get("number_of_seasons"),
                "status": data.get("status"),
            }
            return {
                "source": "tmdb",
                "source_id": str(data["id"]),
                "media_type": kind,
                "title": data.get("title") or data.get("name"),
                "original_title": data.get("original_title") or data.get("original_name"),
                "year": int(date[:4]) if date[:4].isdigit() else None,
                "kind": infer_kind(
                    {
                        "media_type": kind,
                        "genre_ids": [g["id"] for g in data.get("genres", [])],
                        "origin_country": data.get("origin_country"),
                        "original_language": data.get("original_language"),
                    }
                ),
                "summary": data.get("overview") or None,
                "poster_url": _image(data.get("poster_path"), "w500"),
                "backdrop_url": _image(data.get("backdrop_path"), "w1280"),
                "genres": genres,
                "imdb_id": (data.get("external_ids") or {}).get("imdb_id"),
                "detail": {k: v for k, v in detail.items() if v is not None},
            }
    raise SourceError("tmdb", f"no title with id {source_id}", 404)
