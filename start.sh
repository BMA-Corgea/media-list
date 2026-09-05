#!/usr/bin/env bash
#
# media-list launcher.
#
# Cold-boot safe: creates the venv, installs dependencies, builds the frontend if it has
# never been built, and starts the server. The database needs no step here — opening the
# app is what creates it.
#
# NOTE: this script deliberately does NOT free the port. media-list serves a private list;
# it refuses to fight over a socket rather than killing whatever holds it. (Same stance as
# repo-tour, recorded in ../PROJECT_PORTS.md.)

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

HOST="${MEDIA_LIST_HOST:-127.0.0.1}"
PORT="${MEDIA_LIST_PORT:-7799}"

if [ -f .env ]; then
  HOST="$(grep -E '^MEDIA_LIST_HOST=' .env | cut -d= -f2- || true)"; HOST="${HOST:-127.0.0.1}"
  PORT="$(grep -E '^MEDIA_LIST_PORT=' .env | cut -d= -f2- || true)"; PORT="${PORT:-7799}"
  HOST="${MEDIA_LIST_HOST:-$HOST}"
  PORT="${MEDIA_LIST_PORT:-$PORT}"
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  echo "media-list: port ${PORT} is already in use." >&2
  echo "  Something else holds it. This script will not kill it — it serves private data and" >&2
  echo "  refuses to fight over a socket. Stop that process, or set MEDIA_LIST_PORT." >&2
  exit 1
fi

# ── python ────────────────────────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "media-list: creating .venv"
  python3 -m venv .venv
fi
# Self-heal a venv whose interpreter moved with the folder.
if [ ! -x .venv/bin/python ]; then
  echo "media-list: .venv looks broken, rebuilding"
  rm -rf .venv && python3 -m venv .venv
fi
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

# ── frontend ──────────────────────────────────────────────────────────────────────────
if [ ! -d frontend/dist ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "media-list: building the frontend (first run)"
    (cd frontend && npm install --silent && npm run build --silent)
  else
    echo "media-list: npm not found — the API will run but there is no UI to serve." >&2
  fi
fi

echo "media-list: http://${HOST}:${PORT}"
exec ./.venv/bin/python -m uvicorn backend.main:app --host "${HOST}" --port "${PORT}"
