#!/usr/bin/env bash
# ============================================================================
#  WITSML 1.4.1.1 Mudlogging Monitor — one-command launcher (macOS / Linux).
#
#  Usage:
#    ./run.sh            full stack via Docker (recommended)
#    ./run.sh docker     same as above
#    ./run.sh native     run WITHOUT Docker (Python venv + npm + SQLite)
#    ./run.sh down       stop the Docker stack
#
#  Docker mode downloads + builds everything (api, web, mock WITSML store,
#  feed simulator, postgres, redis). Native mode installs the Python and Node
#  dependencies locally and runs the stack with SQLite + an in-process cache.
#  Runtimes themselves (Docker / Python 3.11+ / Node 18+) are NOT auto-installed
#  — the script detects them and prints the official install link if missing.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

cG='\033[0;32m'; cY='\033[1;33m'; cR='\033[0;31m'; cB='\033[0;34m'; cO='\033[0m'
info() { printf "${cB}[run]${cO} %s\n" "$*"; }
ok()   { printf "${cG}[run]${cO} %s\n" "$*"; }
warn() { printf "${cY}[run]${cO} %s\n" "$*"; }
err()  { printf "${cR}[run]${cO} %s\n" "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

ensure_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    ok "created .env from .env.example"
    if have openssl; then
      key=$(openssl rand -hex 32)
      sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${key}|" .env && rm -f .env.bak
      ok "generated a random SECRET_KEY"
    fi
  fi
}

print_urls() {
  printf "\n  ${cG}WITSML Mudlogging Monitor${cO}\n"
  printf "    Web UI        : http://localhost:5173\n"
  printf "    API docs      : http://localhost:8000/docs\n"
  printf "    API health    : http://localhost:8000/health\n"
  printf "    Default login : admin / admin\n\n"
}

run_docker() {
  have docker || { err "Docker is not installed — get it at https://docs.docker.com/get-docker/"; exit 1; }
  docker compose version >/dev/null 2>&1 || { err "Docker Compose v2 not found (update Docker Desktop)."; exit 1; }
  docker info >/dev/null 2>&1 || { err "The Docker daemon isn't running — start Docker Desktop and retry."; exit 1; }
  ensure_env
  print_urls
  info "building + starting the stack (first run pulls/builds images — a few minutes)…"
  exec docker compose up --build
}

stop_docker() { have docker && docker compose down || true; ok "stack stopped"; }

PY_BIN=""
pick_python() {
  for p in python3.12 python3.11 python3 python; do
    have "$p" || continue
    if "$p" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)' 2>/dev/null; then
      PY_BIN="$p"; return 0
    fi
  done
  return 1
}

run_native() {
  pick_python || { err "Python 3.11+ is required for native mode (https://www.python.org/downloads/)."; exit 1; }
  have node || { err "Node.js 18+ is required for native mode (https://nodejs.org)."; exit 1; }
  ensure_env

  local venv="backend/.venv"
  [ -d "$venv" ] || { info "creating Python venv…"; "$PY_BIN" -m venv "$venv"; }
  local vpy="$venv/bin/python"; [ -x "$vpy" ] || vpy="$venv/Scripts/python.exe"
  info "installing backend dependencies…"
  "$vpy" -m pip install -q --upgrade pip
  "$vpy" -m pip install -q -e backend
  if [ ! -d frontend/node_modules ]; then
    info "installing frontend dependencies (npm install)…"
    ( cd frontend && npm install )
  fi

  mkdir -p .run
  local mock_port="${MOCK_PORT:-8090}" api_port="${API_PORT:-8000}"
  export WITSML_URL="http://127.0.0.1:${mock_port}/witsml/store"
  export DATABASE_URL="sqlite+aiosqlite:///./witsml_native.db"
  export REDIS_URL=""                      # empty -> in-process cache fallback
  export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
  export VITE_API_BASE_URL="http://localhost:${api_port}/api"
  export VITE_WS_BASE_URL="ws://localhost:${api_port}"

  local pids=()
  cleanup() { warn "shutting down…"; for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done; }
  trap cleanup EXIT INT TERM

  info "starting mock WITSML store on :${mock_port}…"
  PYTHONPATH="backend:." "$vpy" -m uvicorn mockstore.server:app --host 127.0.0.1 --port "$mock_port" --log-level warning >.run/mock.log 2>&1 &
  pids+=($!); sleep 3
  info "starting feed simulator…"
  PYTHONPATH="backend:." "$vpy" -m simulator.feed_simulator >.run/simulator.log 2>&1 &
  pids+=($!)
  info "starting API on :${api_port}…"
  PYTHONPATH="backend" "$vpy" -m uvicorn app.main:app --host 0.0.0.0 --port "$api_port" >.run/api.log 2>&1 &
  pids+=($!)
  print_urls
  info "backend logs in .run/*.log — starting web dev server (Ctrl-C stops everything)…"
  ( cd frontend && npm run dev -- --host )
}

case "${1:-docker}" in
  docker) run_docker ;;
  native) run_native ;;
  down|stop) stop_docker ;;
  *) err "unknown mode '${1}' (use: docker | native | down)"; exit 1 ;;
esac
