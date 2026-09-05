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
    if status == "seen":
        # Seen rows have no queue_position at all, so ordering by it would be meaningless —
        # most recently finished first is what someone opening an archive wants.
        sql += " ORDER BY watched_at DESC, added_at DESC"
    else:
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


@api.get("/titles/{title_id}")
def get_title(title_id: int) -> JSONResponse:
    rows = query("SELECT * FROM titles WHERE id = ?", (title_id,))
    if not rows:
        raise HTTPException(404, f"no title with id {title_id}")
    return JSONResponse(serialise(rows[0]))


@api.patch("/titles/{title_id}")
def update_title(title_id: int, payload: dict = Body(...)) -> JSONResponse:
    """A sparse update: send only what changes.

    Deliberately sparse so later tickets (T-9's stars and review) can add fields here rather
    than growing a new endpoint each time.
    """
    with connection() as conn:
        row = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"no title with id {title_id}")

        if "why" in payload:
            # Empty means absent, not "". One truthiness test then answers "has a why?"
            # everywhere — the carousel caption, the grid card and the title page.
            why = (payload.get("why") or "").strip() or None
            conn.execute("UPDATE titles SET why = ? WHERE id = ?", (why, title_id))

        # ── rating: the transition out of the queue ──────────────────────────────────
        if "stars" in payload or payload.get("status") == "seen":
            stars = payload.get("stars", row["stars"])
            if stars is not None:
                if not isinstance(stars, int) or isinstance(stars, bool) or not 1 <= stars <= 5:
                    raise HTTPException(400, "stars must be a whole number from 1 to 5")
            if payload.get("status") == "seen" and stars is None:
                raise HTTPException(400, "a rating is required to mark something as seen")
            conn.execute(
                # queue_position is cleared, not kept: a seen title is out of the queue, and
                # holding a stale position would let it sort back in if it ever returned.
                "UPDATE titles SET stars = ?, status = 'seen', watched_at = ?, queue_position = NULL WHERE id = ?",
                (stars, payload.get("watched_at") or now(), title_id),
            )

        if "review" in payload:
            review = (payload.get("review") or "").strip() or None
            conn.execute("UPDATE titles SET review = ? WHERE id = ?", (review, title_id))

        # ── un-watching: back to the end of the queue, opinion intact ────────────────
        if payload.get("status") == "queued":
            top = conn.execute("SELECT COALESCE(MAX(queue_position), 0) FROM titles").fetchone()[0]
            # Stars and review are deliberately NOT cleared. The queue moved on while this was
            # away, so it returns to the END rather than to a stale position, but a rewatch
            # must not erase what was thought the first time.
            conn.execute(
                "UPDATE titles SET status = 'queued', watched_at = NULL, queue_position = ? WHERE id = ?",
                (top + 10, title_id),
            )

        if payload.get("move_to_top"):
            # MIN - 10 rather than renumbering every row: O(1), and it preserves the
            # gap-tolerant scheme T-7's drag reordering is built on.
            floor = conn.execute("SELECT COALESCE(MIN(queue_position), 10) FROM titles").fetchone()[0]
            conn.execute("UPDATE titles SET queue_position = ? WHERE id = ?", (floor - 10, title_id))

        updated = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
    return JSONResponse(serialise(updated))


SPREAD = 10  # the gap left between adjacent positions when the queue is renumbered


def _renumber(conn) -> None:
    """Respread every queued title to multiples of SPREAD, preserving the current order.

    Reached when two neighbours are adjacent integers and no position exists between them.
    Runs inside the caller's transaction, so a failure cannot leave the queue half-renumbered.
    """
    rows = conn.execute(
        "SELECT id FROM titles ORDER BY queue_position IS NULL, queue_position, added_at"
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        conn.execute("UPDATE titles SET queue_position = ? WHERE id = ?", (index * SPREAD, row["id"]))


@api.post("/titles/{title_id}/move")
def move_title(title_id: int, payload: dict = Body(...)) -> JSONResponse:
    """Move a title so it sits immediately after `after_id` (or immediately before `before_id`).

    The caller sends the ids it can SEE, never an index. That is what makes a reorder done
    inside a kind filter safe: the title lands next to exactly those rows, and every row the
    filter was hiding keeps the position it already had.

    Only ONE bound comes from the caller. The other is read from the database — the row that
    is genuinely adjacent right now. Trusting both ends of a caller-supplied pair was a real
    defect: with rows at 5 and 10, every insert "between them" computed the same midpoint 7,
    so four titles ended up sharing position 7 and their order silently fell back to
    `added_at`. Deriving the far bound from the current data means the gap is always the real
    one, and when it is too small to divide the queue renumbers instead of colliding.
    """
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM titles WHERE id = ?", (title_id,)).fetchone():
            raise HTTPException(404, f"no title with id {title_id}")

        def position_of(other):
            if other in (None, "", title_id):
                return None
            row = conn.execute("SELECT queue_position FROM titles WHERE id = ?", (int(other),)).fetchone()
            return row["queue_position"] if row else None

        def bounds():
            """(above, below) — the real gap this title must land in."""
            after = position_of(payload.get("after_id"))
            before = position_of(payload.get("before_id"))
            extremes = conn.execute("SELECT MIN(queue_position), MAX(queue_position) FROM titles").fetchone()
            low, high = (extremes[0] or 0), (extremes[1] or 0)

            if after is not None:
                # Immediately after that row: the far bound is whatever actually follows it.
                nxt = conn.execute(
                    "SELECT MIN(queue_position) FROM titles WHERE queue_position > ? AND id != ?",
                    (after, title_id),
                ).fetchone()[0]
                return after, (nxt if nxt is not None else after + 2 * SPREAD)

            if before is not None:
                prev = conn.execute(
                    "SELECT MAX(queue_position) FROM titles WHERE queue_position < ? AND id != ?",
                    (before, title_id),
                ).fetchone()[0]
                return (prev if prev is not None else before - 2 * SPREAD), before

            # Neither neighbour named: send it to the end.
            return high, high + 2 * SPREAD

        above, below = bounds()
        target = (above + below) // 2

        # Two ways this can be wrong: no integer strictly between the bounds, or an integer
        # that some other row already occupies (which would make the order ambiguous).
        def taken(value):
            return conn.execute(
                "SELECT 1 FROM titles WHERE queue_position = ? AND id != ?", (value, title_id)
            ).fetchone() is not None

        if not (above < target < below) or taken(target):
            _renumber(conn)
            above, below = bounds()
            target = (above + below) // 2

        conn.execute("UPDATE titles SET queue_position = ? WHERE id = ?", (target, title_id))
        rows = conn.execute(
            "SELECT * FROM titles WHERE status = 'queued' ORDER BY queue_position IS NULL, queue_position, added_at"
        ).fetchall()
    return JSONResponse([serialise(r) for r in rows])


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
