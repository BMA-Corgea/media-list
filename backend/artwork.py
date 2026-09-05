"""The local artwork cache.

Every image this app displays is downloaded once and served from disk. Two reasons, and the
second is the important one:

  1. The wall must render with the network off, and remote CDNs go away.
  2. Cached artwork IS the list. `data/` is gitignored precisely so that a public repository
     never reveals what the owner watches — which is why nothing here may write into the
     frontend's public tree.

Files are content-addressed, so re-fetching the same image writes nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import config
from .sources.base import client

#: Downloading a poster is not worth hanging a request over.
MAX_BYTES = 12 * 1024 * 1024


def _extension(url: str) -> str:
    tail = url.rsplit(".", 1)[-1].lower()
    return tail if tail in ("jpg", "jpeg", "png", "webp") else "jpg"


def cached_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return config.art_dir / f"{digest}.{_extension(url)}"


async def cache(url: str | None) -> str | None:
    """Download `url` if it is not already local. Returns the `/art/…` path to serve.

    Returns None rather than raising: a missing poster is a worse-looking card, not a failed
    add. The title is still worth having.
    """
    if not url:
        return None

    destination = cached_path(url)
    if destination.exists() and destination.stat().st_size > 0:
        return f"/art/{destination.name}"  # already here — no second download

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with client() as http:
            response = await http.get(url)
            if not response.is_success or len(response.content) > MAX_BYTES:
                return None
            # Write to a temp name and move, so an interrupted download can never leave a
            # truncated file that the existence check above would then trust forever.
            temporary = destination.with_suffix(destination.suffix + ".part")
            temporary.write_bytes(response.content)
            temporary.replace(destination)
    except Exception:
        return None

    return f"/art/{destination.name}"
