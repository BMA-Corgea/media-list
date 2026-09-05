"""The media-list application.

Serves the built frontend and the API from one process on one port, because a private
single-user app has no reason to make you run two.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .artwork import cache as cache_art
from .config import config
from .db import bootstrap
from .sources import anilist, igdb, tmdb
from .sources.base import SourceError

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> JSONResponse:
    """What is running, and where its data actually lives."""
    return JSONResponse(
        {
            "ok": True,
            "app": "media-list",
            "version": __version__,
            "db_path": str(config.db_path),
            "db_exists": config.db_path.exists(),
            "sources": {
                "tmdb": tmdb.available(),
                "igdb": igdb.available(),
                "pexels": bool(config.pexels_api_key),
            },
        }
    )


@api.get("/search")
async def search(q: str = Query(min_length=1, max_length=120)) -> JSONResponse:
    """Candidates from every configured source, merged and ranked.

    Sources are awaited independently on purpose. One of them dying must not empty the
    result list — an empty list reads as "there are no matches", which would be a lie told
    on the failed source's behalf. A dead source is reported by name instead.

    NOTE: this endpoint deliberately does NOT download artwork. Search is typed into; caching
    every candidate's poster on every keystroke would pull megabytes per character. The cache
    is filled at /details, which is the endpoint that precedes storing a title.
    """
    lookups = []
    if tmdb.available():
        lookups.append(("tmdb", tmdb.search(q)))
    if igdb.available():
        lookups.append(("igdb", igdb.search(q)))

    if not lookups:
        raise HTTPException(503, "no metadata sources are configured — add credentials to .env")

    settled = await asyncio.gather(*(task for _, task in lookups), return_exceptions=True)

    results: list[dict] = []
    status: dict[str, dict] = {}
    for (name, _), outcome in zip(lookups, settled):
        if isinstance(outcome, SourceError):
            status[name] = {"ok": False, "error": outcome.detail}
        elif isinstance(outcome, Exception):
            status[name] = {"ok": False, "error": str(outcome)}
        else:
            status[name] = {"ok": True, "count": len(outcome)}
            results.extend(outcome)

    # Popularity is the only ordering signal both sources share. Exact title matches are
    # lifted above it, because someone typing a full title wants that title, not the most
    # popular thing containing those words.
    needle = q.strip().lower()
    results.sort(key=lambda r: (r["title"].lower() != needle, -float(r.get("popularity") or 0)))

    disabled = [n for n in ("tmdb", "igdb") if n not in status]
    return JSONResponse({"query": q, "results": results, "sources": status, "disabled": disabled})


@api.get("/details/{source}/{source_id}")
async def details(source: str, source_id: str, media_type: str | None = None) -> JSONResponse:
    """The full record for one candidate, with its artwork pulled local.

    This is what T-4 calls before storing a title, which is why the caching happens here.

    `media_type` is REQUIRED for TMDB and must be carried through from the search result —
    see the namespace note in `sources/tmdb.details`. Anything that persists a TMDB title
    has to persist its media_type too, or it will not be able to refresh it later.
    """
    try:
        if source == "tmdb":
            record = await tmdb.details(source_id, media_type)
            if record["kind"] == "anime":
                # Decorate only. A fuzzy AniList match may add a studio or an episode count;
                # it may never rename a title the user already picked off a poster.
                extras = await anilist.enrich(record.get("original_title") or record["title"])
                record["anilist_id"] = extras.pop("anilist_id", None)
                record["detail"] = {**record.get("detail", {}), **extras}
        elif source == "igdb":
            record = await igdb.details(source_id)
        else:
            raise HTTPException(404, f"unknown source {source!r}")
    except SourceError as error:
        # A caller mistake is not a gateway failure. 400 and 404 belong to whoever called
        # this; 401/429/5xx from upstream become 502, because from the caller's side the
        # gateway is what failed.
        status = error.status if error.status in (400, 404) else 502
        raise HTTPException(status, error.as_dict()) from error

    record["poster_path"] = await cache_art(record.get("poster_url"))
    record["backdrop_path"] = await cache_art(record.get("backdrop_url"))
    return JSONResponse(record)


def create_app() -> FastAPI:
    app = FastAPI(title="media-list", version=__version__, docs_url="/api/docs")

    # Opening the app is what builds the database. Nothing else to run, ever.
    bootstrap()

    app.include_router(api)

    # Cached artwork is served from the gitignored data directory rather than the frontend's
    # public tree — the wall must work offline, and these files reveal what is on the list.
    app.mount("/art", StaticFiles(directory=config.art_dir), name="art")

    dist = config.frontend_dist
    # Resolved once: the containment check below compares against the real path, so a
    # symlinked or relative dist cannot quietly widen what is reachable.
    dist_root = dist.resolve()
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            """Serve the app for any non-API path so client-side routing works.

            Registered last and guarded against `/api` and `/art`: a catch-all that swallowed
            those would turn every JSON endpoint into HTML, which fails silently and is
            miserable to debug.
            """
            if full_path.startswith(("api/", "art/")):
                return JSONResponse({"detail": "Not Found"}, status_code=404)

            # CONTAINMENT. `dist / full_path` alone is a path traversal: a client that sends
            # the path raw (curl --path-as-is; browsers normalise, other clients do not) can
            # walk out of dist with `..` and read anything the process can — this served the
            # real .env, API keys and all, before it was fixed. Resolve, then require the
            # result to still be inside dist. Symlinks resolve too, so a link planted in the
            # build output cannot escape either.
            candidate = (dist / full_path).resolve()
            inside = candidate == dist_root or dist_root in candidate.parents
            if full_path and inside and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
