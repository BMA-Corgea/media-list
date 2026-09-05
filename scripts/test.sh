#!/usr/bin/env bash
#
# media-list test runner (T-13, AC1; T-14 AC5 added the --browsers mode).
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
# `--browsers` runs the T-14 three-engine suite (tests/browser/, driven by Playwright)
# INSTEAD of pytest — its own named command, deliberately not folded into the default run.
# The default `scripts/test.sh` above is the ~8 second loop T-13 built; a browser run costs
# real seconds per engine and downloads real browser binaries on a first run, so it stays
# behind this flag rather than becoming part of every invocation. Any argument after
# `--browsers` is forwarded to `playwright test` as-is, e.g.
# `scripts/test.sh --browsers --project=chromium` or `scripts/test.sh --browsers -g wheel`.
#
# Any other argument (with no `--browsers`) is forwarded to pytest as-is, e.g.
# `scripts/test.sh -k queue_order` or `scripts/test.sh -x`.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BROWSERS=0
PYTEST_ARGS=()
PLAYWRIGHT_ARGS=()
COVERAGE=0
for arg in "$@"; do
  if [ "$BROWSERS" -eq 1 ]; then
    PLAYWRIGHT_ARGS+=("$arg")
  elif [ "$arg" = "--browsers" ]; then
    BROWSERS=1
  elif [ "$arg" = "--cov" ]; then
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

# ── --browsers: a separate, self-contained mode ─────────────────────────────────────────
if [ "$BROWSERS" -eq 1 ]; then
  echo "media-list: --browsers — Chromium, Firefox, WebKit (T-14 AC2)"

  # AC1: @playwright/test is a real frontend/package.json devDependency now — no more
  # borrowing ../GLP-Strong-App's install. `npm install` here is a no-op once node_modules
  # already matches package-lock.json.
  (cd frontend && npm install --silent)

  # Browser BINARIES only — never `--with-deps` here, which would shell out to `sudo
  # apt-get` unprompted. WebKit's own OS-level shared-library dependencies (distinct from
  # the browser binary itself) are a one-time, human-run `sudo npx playwright install-deps`
  # in frontend/ — see kb/wiki/lessons.md's T-14 entry if that browser fails to LAUNCH
  # (not fails a test) with a "Host system is missing dependencies" error. Chromium and
  # WebKit are typically already cached; Firefox is the one real download the first time.
  (cd frontend && npx playwright install chromium firefox webkit)

  # The SPA route only exists if frontend/dist exists AT THE TIME backend.main is first
  # imported (create_app() checks `dist.is_dir()` once) — same rule tests/conftest.py
  # documents for the pytest suite. global-setup.js does not build it; this does, so a
  # first-time `--browsers` run behaves like a first-time `start.sh` run.
  if [ ! -d frontend/dist ]; then
    echo "media-list: building the frontend (first run)"
    (cd frontend && npm run build --silent)
  fi

  OWNER_DB="data/media-list.db"
  owner_db_state() {
    if [ -f "$OWNER_DB" ]; then
      stat -c %Y "$OWNER_DB" 2>/dev/null || stat -f %m "$OWNER_DB"
    else
      echo "absent"
    fi
  }
  BEFORE_DB_STATE="$(owner_db_state)"

  set +e
  (cd frontend && npx playwright test "${PLAYWRIGHT_ARGS[@]}")
  PLAYWRIGHT_STATUS=$?
  set -e

  AFTER_DB_STATE="$(owner_db_state)"
  if [ "$AFTER_DB_STATE" != "$BEFORE_DB_STATE" ]; then
    echo "media-list: FATAL — ${OWNER_DB} changed during the browser run" \
         "(${BEFORE_DB_STATE} -> ${AFTER_DB_STATE}). global-setup.js's scratch MEDIA_LIST_DB" \
         "should make this structurally impossible — treat this as a real bug." >&2
    exit 1
  fi

  if [ "$PLAYWRIGHT_STATUS" -ne 0 ]; then
    echo "media-list: browser suite failed (exit ${PLAYWRIGHT_STATUS})" >&2
  else
    # Say what actually RAN, never a fixed number of engines. AC2 was amended to Chromium
    # + Firefox (WebKit cannot launch on Ubuntu 24.04 — see .autodev/specs/T-14.md), and a
    # message that claims three when two ran is the same class of lie as a test that
    # cannot fail. Playwright already prints the per-project results above this line.
    echo "media-list: browser suite passed, ${OWNER_DB} untouched"
  fi
  exit "$PLAYWRIGHT_STATUS"
fi

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
