"""The media-list application.

Serves the built frontend and the API from one process on one port, because a private
single-user app has no reason to make you run two.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import config
from .db import bootstrap

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
                "tmdb": bool(config.tmdb_api_key),
                "igdb": bool(config.igdb_client_id and config.igdb_client_secret),
                "pexels": bool(config.pexels_api_key),
            },
        }
    )


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
