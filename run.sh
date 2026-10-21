#!/usr/bin/env bash
# Start AFTERIMAGE with one command: installs what is missing, then runs the backend
# (http://127.0.0.1:8000) and the dashboard (http://localhost:5173). Press Ctrl+C to stop both.
#
#   ./run.sh                                   # simulated agent works with no key; add keys in Settings
#   AFTERIMAGE_LLM_PROVIDER=gemini ./run.sh    # any AFTERIMAGE_* setting is passed through
#   AFTERIMAGE_NO_BROWSER=1 ./run.sh           # don't open the browser
#
# macOS and Linux. On Windows, follow docs/USER_MANUAL.md (or run this from WSL).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT=8000
FRONTEND_URL="http://localhost:5173"

say()  { printf '\033[1;36m[afterimage]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[afterimage]\033[0m %s\n' "$*" >&2; exit 1; }

# -- requirements ---------------------------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.12 or newer is required (https://www.python.org/downloads/)."

command -v node >/dev/null 2>&1 || fail "Node.js 22.12 or newer is required (https://nodejs.org/)."
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=12)?0:1)' ||
  fail "Node.js 22.12 or newer is required; found $(node --version)."
command -v npm >/dev/null 2>&1 || fail "npm was not found (it normally comes with Node.js)."

port_free() { "$PYTHON" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1])))' "$1" 2>/dev/null; }
port_free "$BACKEND_PORT" || fail "Port $BACKEND_PORT is already in use. Is AFTERIMAGE already running in another terminal?"
port_free 5173 || fail "Port 5173 is already in use. Is AFTERIMAGE already running in another terminal?"

# -- install (only when something is missing or the dependency lists changed) ----------
stamp_of() { cat "$@" | cksum; }

if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  say "Creating the Python environment (backend/.venv)…"
  "$PYTHON" -m venv "$BACKEND/.venv"
fi
REQ_STAMP="$(stamp_of "$BACKEND/requirements.txt")"
if [ "$(cat "$BACKEND/.venv/.afterimage-installed" 2>/dev/null || true)" != "$REQ_STAMP" ]; then
  say "Installing backend dependencies (first run takes a minute)…"
  "$BACKEND/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$BACKEND/requirements.txt"
  printf '%s' "$REQ_STAMP" > "$BACKEND/.venv/.afterimage-installed"
fi

NPM_STAMP="$(stamp_of "$FRONTEND/package-lock.json")"
if [ ! -x "$FRONTEND/node_modules/.bin/vite" ] ||
   [ "$(cat "$FRONTEND/node_modules/.afterimage-installed" 2>/dev/null || true)" != "$NPM_STAMP" ]; then
  say "Installing frontend dependencies (first run takes a minute)…"
  (cd "$FRONTEND" && npm ci --no-audit --no-fund --loglevel=error)
  printf '%s' "$NPM_STAMP" > "$FRONTEND/node_modules/.afterimage-installed"
fi

# -- run --------------------------------------------------------------------------------
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  trap - INT TERM EXIT
  say "Stopping…"
  for pid in $FRONTEND_PID $BACKEND_PID; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

say "Starting the backend on http://127.0.0.1:$BACKEND_PORT …"
(cd "$BACKEND" && exec .venv/bin/uvicorn afterimage.main:create_app --factory --host 127.0.0.1 --port "$BACKEND_PORT") &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if "$PYTHON" -c 'import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1)' \
       "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null; then
    break
  fi
  kill -0 "$BACKEND_PID" 2>/dev/null || fail "The backend stopped during startup; see the error above."
  sleep 1
done

say "Starting the dashboard on $FRONTEND_URL …"
(cd "$FRONTEND" && exec node_modules/.bin/vite) &
FRONTEND_PID=$!

if [ -z "${AFTERIMAGE_NO_BROWSER:-}" ]; then
  (sleep 2
   if command -v open >/dev/null 2>&1; then open "$FRONTEND_URL"
   elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$FRONTEND_URL" >/dev/null 2>&1
   fi) &
fi

say "AFTERIMAGE is running: $FRONTEND_URL  (Ctrl+C to stop)"
say "No API key needed for the simulated agent. To use Gemini or Claude: Settings → LLM agent configuration → Add API key."

# Stop everything if either server exits.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
fail "A server stopped unexpectedly; see the output above."
