"""IGDB — video games.

Chosen over RAWG for one reason that decided the whole product: IGDB serves PORTRAIT box art
at roughly 2:3, the same shape as a film poster, so a game sits on the same carousel as
everything else. RAWG's primary image is a landscape screenshot, which would have forced
either letterboxed cards or a second card shape on the wall.

It authenticates through Twitch rather than with a plain key, which is the only awkward part.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..config import config
from .base import IGDB_LIMIT, SourceError, client, raise_for

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
BASE = "https://api.igdb.com/v4"
COVER = "https://images.igdb.com/igdb/image/upload/t_cover_big"
SCREEN = "https://images.igdb.com/igdb/image/upload/t_screenshot_big"

#: Lives beside the database, inside gitignored `data/`, at 0600. A bearer token is a
#: credential; it does not belong anywhere a `git add -A` could reach it.
TOKEN_CACHE = config.data_dir / "igdb-token.json"


def available() -> bool:
    return bool(config.igdb_client_id and config.igdb_client_secret)


def _read_cached_token() -> str | None:
    try:
        cached = json.loads(TOKEN_CACHE.read_text())
    except (OSError, ValueError):
        return None
    # 60s of headroom so a token cannot expire between the check and the call that uses it.
    if cached.get("expires_at", 0) - 60 > time.time():
        return cached.get("access_token")
    return None


def _write_cached_token(token: str, expires_in: int) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps({"access_token": token, "expires_at": time.time() + expires_in}))
    os.chmod(TOKEN_CACHE, 0o600)


async def token(force: bool = False) -> str:
    """A bearer token, fetched once and reused until it expires.

    Twitch tokens last ~60 days. Exchanging on every request would be both slow and a good
    way to get rate limited for no reason.
    """
    if not available():
        raise SourceError("igdb", "no IGDB_CLIENT_ID / IGDB_CLIENT_SECRET in .env")
    if not force:
        cached = _read_cached_token()
        if cached:
            return cached

    async with client() as http:
        async with IGDB_LIMIT.slot():
            response = await http.post(
                TOKEN_URL,
                params={
                    "client_id": config.igdb_client_id,
                    "client_secret": config.igdb_client_secret,
                    "grant_type": "client_credentials",
                },
            )
        raise_for("igdb", response)
        payload = response.json()

    access = payload.get("access_token")
    if not access:
        raise SourceError("igdb", "Twitch returned no access_token")
    _write_cached_token(access, int(payload.get("expires_in", 3600)))
    return access


async def _query(body: str, *, retry: bool = True) -> list[dict]:
    """POST an apicalypse query. A 401 means the cached token died; refresh once and retry."""
    # `token()` may itself go to Twitch, and it must do so BEFORE the slot is taken: an
    # unrelated outbound call made while holding an open-request slot would have the limiter
    # counting one request and two leaving.
    bearer = await token()
    async with client() as http:
        async with IGDB_LIMIT.slot():
            response = await http.post(
                f"{BASE}/games",
                content=body,
                headers={
                    "Client-ID": config.igdb_client_id or "",
                    "Authorization": f"Bearer {bearer}",
                    "Accept": "application/json",
                },
            )
        if response.status_code == 401 and retry:
            await token(force=True)
            return await _query(body, retry=False)
        raise_for("igdb", response)
        return response.json()


def _normalise(game: dict) -> dict:
    cover = (game.get("cover") or {}).get("image_id")
    shots = game.get("screenshots") or []
    released = game.get("first_release_date")
    return {
        "source": "igdb",
        "source_id": str(game["id"]),
        "media_type": "game",
        "title": game.get("name") or "",
        "original_title": None,
        "year": time.gmtime(released).tm_year if released else None,
        "kind": "game",
        "summary": game.get("summary") or None,
        # Portrait box art. This is the line that made IGDB the right choice.
        "poster_url": f"{COVER}/{cover}.jpg" if cover else None,
        "backdrop_url": f"{SCREEN}/{shots[0]['image_id']}.jpg" if shots and shots[0].get("image_id") else None,
        "popularity": game.get("total_rating_count") or 0,
    }


FIELDS = "name, summary, first_release_date, cover.image_id, screenshots.image_id, total_rating_count"


async def search(query: str) -> list[dict]:
    escaped = query.replace('"', '\\"')
    body = f'search "{escaped}"; fields {FIELDS}; limit 12;'
    return [_normalise(g) for g in await _query(body)]


async def details(source_id: str) -> dict:
    body = (
        f"fields {FIELDS}, slug, genres.name, platforms.abbreviation, "
        f"involved_companies.company.name, involved_companies.developer; "
        f"where id = {int(source_id)}; limit 1;"
    )
    rows = await _query(body)
    if not rows:
        raise SourceError("igdb", f"no game with id {source_id}", 404)
    game = rows[0]
    record = _normalise(game)

    developers = [
        c["company"]["name"]
        for c in game.get("involved_companies", [])
        if c.get("developer") and c.get("company", {}).get("name")
    ]
    record.update(
        {
            "genres": [g["name"] for g in game.get("genres", [])],
            # Games have no IMDb entry at all. This is null by design; the title page links
            # to IGDB instead, and the schema allows it.
            "imdb_id": None,
            "detail": {
                "platforms": [p["abbreviation"] for p in game.get("platforms", []) if p.get("abbreviation")],
                "developer": developers[0] if developers else None,
                "igdb_url": f"https://www.igdb.com/games/{game['slug']}" if game.get("slug") else None,
            },
        }
    )
    return record
