#!/usr/bin/env bash
#
# media-list test runner (T-13, AC1).
#
# The one command: `scripts/test.sh`. Exits non-zero on any test failure, and separately on
# any sign that the suite touched the owner's real database (AC5) — either one fails the
# whole run.
#
# Cold-boot safe like start.sh: creates/reuses .venv, installs both requirement files, then
# runs pytest. No port is ever bound — the API tests drive the ASGI app in-process through
# `starlette.testclient.TestClient`, so there is nothing here to collide with a running
# server on 7799 and nothing that needs `ss`/`pkill`.
#
# `--live` opts into tests marked `@pytest.mark.live` (real TMDB/AniList/IGDB network calls,
# real credentials required) — skipped by default (AC6). Any other argument is forwarded to
# pytest as-is, e.g. `scripts/test.sh -k queue_order` or `scripts/test.sh -x`.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTEST_ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--live" ]; then
    PYTEST_ARGS+=("--live")
  else
    PYTEST_ARGS+=("$arg")
  fi
done

# ── python ────────────────────────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "media-list: creating .venv"
  python3 -m venv .venv
fi
if [ ! -x .venv/bin/python ]; then
  echo "media-list: .venv looks broken, rebuilding"
  rm -rf .venv && python3 -m venv .venv
fi
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt -r requirements-dev.txt

# ── AC5, belt and suspenders ─────────────────────────────────────────────────────────
# The real guarantee is structural: tests/conftest.py points MEDIA_LIST_DB at a throwaway
# tmp path before backend.config is ever imported, so the pytest process never opens
# data/media-list.db at all. This is the outside check that proves it: if the owner's real
# database happens to exist (this worktree has no data/ at all, so on a fresh checkout the
# block below is a no-op — the file genuinely does not exist to have a mtime), record its
# mtime before and after and fail loudly if it moved even one second.
OWNER_DB="data/media-list.db"
BEFORE_MTIME=""
if [ -f "$OWNER_DB" ]; then
  BEFORE_MTIME="$(stat -c %Y "$OWNER_DB" 2>/dev/null || stat -f %m "$OWNER_DB")"
fi

# ── run ───────────────────────────────────────────────────────────────────────────────
set +e
./.venv/bin/python -m pytest "${PYTEST_ARGS[@]}"
PYTEST_STATUS=$?
set -e

TOUCHED_OWNER_DB=0
if [ -n "$BEFORE_MTIME" ]; then
  AFTER_MTIME="$(stat -c %Y "$OWNER_DB" 2>/dev/null || stat -f %m "$OWNER_DB")"
  if [ "$AFTER_MTIME" != "$BEFORE_MTIME" ]; then
    echo "media-list: FATAL — ${OWNER_DB}'s mtime changed during the test run" \
         "(${BEFORE_MTIME} -> ${AFTER_MTIME}). The suite touched the owner's real database." >&2
    TOUCHED_OWNER_DB=1
  fi
fi

if [ "$PYTEST_STATUS" -ne 0 ]; then
  echo "media-list: tests failed (exit ${PYTEST_STATUS})" >&2
elif [ "$TOUCHED_OWNER_DB" -eq 0 ]; then
  echo "media-list: all tests passed, ${OWNER_DB} untouched"
fi

if [ "$PYTEST_STATUS" -ne 0 ] || [ "$TOUCHED_OWNER_DB" -ne 0 ]; then
  exit 1
fi
exit 0
