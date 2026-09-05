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
# real credentials required) — skipped by default (AC6).
#
# `--cov` expands to `--cov=backend --cov-report=term-missing`: what this suite does and does
# not freeze, on demand. Off by default — coverage is a reading, not a gate, and nothing here
# fails on a number. It is also the only thing that invokes pytest-cov, which is why that
# dependency is in requirements-dev.txt at all (T-13 round 2).
#
# Any other argument is forwarded to pytest as-is, e.g. `scripts/test.sh -k queue_order`
# or `scripts/test.sh -x`.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTEST_ARGS=()
COVERAGE=0
for arg in "$@"; do
  if [ "$arg" = "--cov" ]; then
    COVERAGE=1
  else
    PYTEST_ARGS+=("$arg")
  fi
done
if [ "$COVERAGE" -eq 1 ]; then
  PYTEST_ARGS+=("--cov=backend" "--cov-report=term-missing")
fi

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
# data/media-list.db at all. This is the outside check that proves it: record what the
# owner's database looks like before the run and again after, and fail loudly on any
# difference — a moved mtime, a deletion, or a file appearing where there was none.
#
# Absence is a state, not a reason to skip the check. Recording "" for "the file is not
# there" meant the after-check never ran on a fresh clone or after `rm -rf data` — so a
# suite that CREATED the owner's database where none existed was reported as clean, in
# exactly the fresh-checkout case AC5 names as one of its two proof cases (T-13 round 2).
OWNER_DB="data/media-list.db"
owner_db_state() {
  if [ -f "$OWNER_DB" ]; then
    stat -c %Y "$OWNER_DB" 2>/dev/null || stat -f %m "$OWNER_DB"
  else
    echo "absent"
  fi
}
BEFORE_DB_STATE="$(owner_db_state)"

# ── run ───────────────────────────────────────────────────────────────────────────────
set +e
./.venv/bin/python -m pytest "${PYTEST_ARGS[@]}"
PYTEST_STATUS=$?
set -e

AFTER_DB_STATE="$(owner_db_state)"
TOUCHED_OWNER_DB=0
if [ "$AFTER_DB_STATE" != "$BEFORE_DB_STATE" ]; then
  TOUCHED_OWNER_DB=1
  if [ "$BEFORE_DB_STATE" = "absent" ]; then
    echo "media-list: FATAL — the test run CREATED ${OWNER_DB}, which did not exist before." \
         "The suite is writing to the owner's real database path (T-13 AC5)." >&2
  elif [ "$AFTER_DB_STATE" = "absent" ]; then
    echo "media-list: FATAL — ${OWNER_DB} was DELETED during the test run." >&2
  else
    echo "media-list: FATAL — ${OWNER_DB}'s mtime changed during the test run" \
         "(${BEFORE_DB_STATE} -> ${AFTER_DB_STATE}). The suite touched the owner's real database." >&2
  fi
fi

if [ "$PYTEST_STATUS" -ne 0 ]; then
  echo "media-list: tests failed (exit ${PYTEST_STATUS})" >&2
elif [ "$TOUCHED_OWNER_DB" -eq 0 ]; then
  if [ "$BEFORE_DB_STATE" = "absent" ]; then
    echo "media-list: all tests passed, ${OWNER_DB} still absent (never created)"
  else
    echo "media-list: all tests passed, ${OWNER_DB} untouched (mtime ${BEFORE_DB_STATE})"
  fi
fi

if [ "$PYTEST_STATUS" -ne 0 ] || [ "$TOUCHED_OWNER_DB" -ne 0 ]; then
  exit 1
fi
exit 0
