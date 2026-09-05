#!/usr/bin/env python3
"""Fetch the ambient chrome imagery, once.

Pexels is used ONLY for texture — the ground behind the carousel, an empty state, an archive
header. It is never a source of title artwork: stock photography cannot supply key art, and a
poster wall made of stock photos is the spreadsheet problem wearing a nicer coat.

Idempotent: a slot whose file already exists is skipped, so re-running costs no API quota and
does not churn committed files.

    ./.venv/bin/python scripts/fetch-chrome.py [--force]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from backend.config import config

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "chrome"

#: slug -> (search query, why this image is here at all)
SLOTS = {
    "empty-wall": (
        "empty cinema seats dark",
        "the empty state — a room waiting for something to start, which is exactly what an "
        "empty watchlist is",
    ),
    "carousel-ground": (
        "dark textured wall abstract",
        "the ground behind the carousel — texture only, deliberately without a subject, so it "
        "never competes with the poster art in front of it",
    ),
    "archive-header": (
        "old film reels shelf",
        "the Seen archive header — a shelf of finished things, which is what the archive is",
    ),
}


def fetch() -> int:
    if not config.pexels_api_key:
        print("PEXELS_API_KEY is not set — nothing fetched.", file=sys.stderr)
        print("The app renders fine without these; the surfaces just fall back to flat tokens.", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    credits_path = OUT / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else []
    by_slug = {c["slug"]: c for c in credits}
    force = "--force" in sys.argv

    with httpx.Client(timeout=30, headers={"Authorization": config.pexels_api_key}) as http:
        for slug, (query, why) in SLOTS.items():
            destination = OUT / f"{slug}.jpg"
            if destination.exists() and not force:
                print(f"  {slug}: already here, skipped")
                continue

            response = http.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1, "orientation": "landscape", "size": "large"},
            )
            response.raise_for_status()
            photos = response.json().get("photos") or []
            if not photos:
                print(f"  {slug}: nothing found for {query!r}", file=sys.stderr)
                continue

            photo = photos[0]
            # Pexels' own sized URL rather than the original: this is a background, and
            # shipping a 6000px original to be blurred behind a scrim would be silly.
            image = http.get(photo["src"]["large2x"])
            image.raise_for_status()
            destination.write_bytes(image.content)

            by_slug[slug] = {
                "slug": slug,
                "creator": photo["photographer"],
                "license": "Pexels",
                "source": photo["url"],
                "photographer_url": photo["photographer_url"],
                "alt": photo.get("alt") or query,
                "why": why,
            }
            print(f"  {slug}: {photo['photographer']} — {len(image.content) // 1024} kB")

    credits_path.write_text(json.dumps([by_slug[s] for s in SLOTS if s in by_slug], indent=2) + "\n")
    print(f"credits written: {credits_path.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(fetch())
