"""The media-list application.

Serves the built frontend and the API from one process on one port, because a private
single-user app has no reason to make you run two.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .artwork import cache as cache_art
from .config import config
from .db import bootstrap, connection, execute, query
from .sources import anilist, igdb, tmdb
from .titles import now, serialise
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

    `media_type` is REQUIRED for TMDB and must be carried through from the search result —
    see the namespace note in `sources/tmdb.details`. Anything that persists a TMDB title
    has to persist its media_type too, or it will not be able to refresh it later.
    """
    try:
        return JSONResponse(await _fetch(source, source_id, media_type))
    except SourceError as error:
        status = error.status if error.status in (400, 404) else 502
        raise HTTPException(status, error.as_dict()) from error


async def _fetch(source: str, source_id: str, media_type: str | None) -> dict:
    """The full record for one candidate, artwork already pulled local by /api/details."""
    if source == "tmdb":
        record = await tmdb.details(source_id, media_type)
        if record["kind"] == "anime":
            extras = await anilist.enrich(record.get("original_title") or record["title"])
            record["anilist_id"] = extras.pop("anilist_id", None)
            record["detail"] = {**record.get("detail", {}), **extras}
    elif source == "igdb":
        record = await igdb.details(source_id)
    else:
        raise HTTPException(404, f"unknown source {source!r}")

    record["poster_path"] = await cache_art(record.get("poster_url"))
    record["backdrop_path"] = await cache_art(record.get("backdrop_url"))
    return record


@api.get("/titles")
def list_titles(status: str | None = None) -> JSONResponse:
    """The list, in queue order. Unpositioned rows sort last rather than first."""
    sql = "SELECT * FROM titles"
    params: tuple = ()
    if status in ("queued", "seen"):
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY queue_position IS NULL, queue_position, added_at"
    return JSONResponse([serialise(r) for r in query(sql, params)])


@api.post("/titles")
async def add_title(payload: dict = Body(...)) -> JSONResponse:
    """Store a candidate the user picked. Everything but `why` comes from the source."""
    source = payload.get("source")
    source_id = str(payload.get("source_id") or "")
    if not source or not source_id:
        raise HTTPException(400, "source and source_id are required")

    try:
        record = await _fetch(source, source_id, payload.get("media_type"))
    except SourceError as error:
        status = error.status if error.status in (400, 404) else 502
        raise HTTPException(status, error.as_dict()) from error

    # T-3's obligation (kb/CURRENT-WORK.md): a stored TMDB title MUST remember which
    # namespace its id belongs to. Without it a later refresh of id 30991 returns
    # "The Curse of the Living Corpse" instead of Cowboy Bebop.
    detail = {**record.get("detail", {}), "media_type": record.get("media_type")}

    with connection() as conn:
        # Gap-tolerant, as T-7's reordering requires: append at max + 10, never renumber.
        top = conn.execute("SELECT COALESCE(MAX(queue_position), 0) FROM titles").fetchone()[0]
        try:
            cursor = conn.execute(
                """INSERT INTO titles (source, source_id, imdb_id, anilist_id, title,
                        original_title, year, kind, summary, poster_path, backdrop_path,
                        genres, detail, why, status, queue_position, added_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)""",
                (
                    record["source"], record["source_id"], record.get("imdb_id"),
                    record.get("anilist_id"), record["title"], record.get("original_title"),
                    record.get("year"), record["kind"], record.get("summary"),
                    record.get("poster_path"), record.get("backdrop_path"),
                    json.dumps(record.get("genres") or []), json.dumps(detail),
                    (payload.get("why") or "").strip() or None,
                    top + 10, now(),
                ),
            )
        except sqlite3.IntegrityError:
            # Caught rather than pre-checked: the unique index makes this race-safe, a
            # SELECT-then-INSERT would not be.
            existing = conn.execute(
                "SELECT id, title FROM titles WHERE source = ? AND source_id = ?",
                (record["source"], record["source_id"]),
            ).fetchone()
            raise HTTPException(409, {
                "detail": f"{existing['title']} is already on your list",
                "existing_id": existing["id"],
            }) from None
        stored = conn.execute("SELECT * FROM titles WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return JSONResponse(serialise(stored), status_code=201)


@api.delete("/titles/{title_id}")
def remove_title(title_id: int) -> JSONResponse:
    """Remove a title. Cached artwork is deliberately left alone — files are addressed by
    content, so another title may legitimately be using the same image."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM titles WHERE id = ?", (title_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, f"no title with id {title_id}")
    return JSONResponse({"removed": title_id})


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
