"""CSV export and the resolver import.

The owner has no existing list and intends to generate one with a chatbot, so the input is loose
BY DESIGN. This is a resolver, not a loader: rows are matched against the sources, anything
ambiguous comes back for a human choice, and nothing is dropped in silence.

The column contract is published in README.md, which the owner has been told to rely on. It is
reproduced here as the single source and must not drift from that document.
"""

from __future__ import annotations

import csv
import io
import json
import re

#: The exact export header, in the README's order.
#:
#: `isbn` joined in T-16, on the owner's explicit instruction ("Add the isbn column"), and
#: sits with the other identifiers rather than at the end because that is where it reads.
#: ADDING a column does not break an older file: `parse` reads by header NAME, so an export
#: taken before T-16 still imports — there is a test that holds that (`tests/fixtures/`).
COLUMNS = [
    "title", "year", "kind", "why", "status", "stars", "queue_position",
    "tmdb_id", "igdb_id", "imdb_id", "isbn", "added_at", "watched_at", "review",
]

KINDS = {"anime", "movie", "live-action", "game", "book"}


def export_rows(rows) -> str:
    """Every column the README promises, RFC4180-quoted, UTF-8."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "title": row["title"],
            "year": row["year"] or "",
            "kind": row["kind"],
            "why": row["why"] or "",
            "status": row["status"],
            "stars": row["stars"] if row["stars"] is not None else "",
            "queue_position": row["queue_position"] if row["queue_position"] is not None else "",
            # A game has no TMDB id. Writing its IGDB id under a tmdb_id header would be a
            # lie that survives the round trip, so the column stays blank and `source` is
            # recovered on import from which id column is populated.
            # One id column per source. Without igdb_id a game would export with NO id at
            # all and have to be re-resolved by search on the way back in, which makes the
            # round trip approximate instead of exact.
            "tmdb_id": row["source_id"] if row["source"] == "tmdb" else "",
            "igdb_id": row["source_id"] if row["source"] == "igdb" else "",
            "imdb_id": row["imdb_id"] or "",
            # A book has no id column of its own, so this IS its id on the way back in:
            # an ISBN names one edition, an edition belongs to one work, and the resolver
            # spends it exactly the way it spends a tmdb_id. Blank for everything else.
            "isbn": row["isbn"] or "",
            "added_at": row["added_at"] or "",
            "watched_at": row["watched_at"] or "",
            "review": row["review"] or "",
        })
    return buffer.getvalue()


def _clean(text: str) -> str:
    """Make chatbot output parseable without asking the user to tidy it first.

    The README tells the owner to paste raw output, and raw output arrives with a BOM, or wrapped
    in a ``` fence, or both. Refusing that would be technically correct and practically
    useless.
    """
    text = text.lstrip("﻿")
    fence = re.match(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?\s*```\s*$", text, re.S)
    if fence:
        text = fence.group(1)
    return text.strip("\n")


def parse(text: str) -> tuple[list[dict], list[str]]:
    """(rows, problems). Only `title` is required; everything else is optional."""
    text = _clean(text)
    if not text.strip():
        return [], ["the file is empty"]

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["no header row found"]

    headers = [(h or "").strip().lower() for h in reader.fieldnames]
    if "title" not in headers:
        return [], [f"no 'title' column — found: {', '.join(headers) or '(nothing)'}"]

    rows, problems = [], []
    for number, raw in enumerate(reader, start=2):
        record = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        title = record.get("title", "")
        if not title:
            problems.append(f"row {number}: no title — skipped")
            continue

        year = record.get("year", "")
        kind = record.get("kind", "").lower()
        if kind and kind not in KINDS:
            problems.append(f"row {number}: unknown kind {kind!r} — will be inferred instead")
            kind = ""

        rows.append({
            "line": number,
            "title": title,
            "year": int(year) if year[:4].isdigit() else None,
            "kind": kind or None,
            "why": record.get("why") or None,
            "status": record.get("status") or None,
            "stars": int(record["stars"]) if record.get("stars", "").isdigit() else None,
            "queue_position": int(record["queue_position"]) if record.get("queue_position", "").isdigit() else None,
            "tmdb_id": record.get("tmdb_id") or None,
            "igdb_id": record.get("igdb_id") or None,
            "imdb_id": record.get("imdb_id") or None,
            "isbn": record.get("isbn") or None,
            "added_at": record.get("added_at") or None,
            "watched_at": record.get("watched_at") or None,
            "review": record.get("review") or None,
        })
    return rows, problems


def score(candidate: dict, row: dict) -> float:
    """How well a search result answers a CSV row. Used only to rank, never to auto-accept."""
    points = 0.0
    a, b = candidate["title"].lower().strip(), row["title"].lower().strip()
    if a == b:
        points += 100
    elif b in a or a in b:
        points += 55
    if row["year"] and candidate.get("year"):
        gap = abs(candidate["year"] - row["year"])
        points += 40 if gap == 0 else (18 if gap == 1 else -12 * min(gap, 4))
    if row["kind"] and candidate.get("kind") == row["kind"]:
        points += 25
    points += min(float(candidate.get("popularity") or 0), 60) / 12
    return points
