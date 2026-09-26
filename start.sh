#!/usr/bin/env bash
# Agent HQ launcher: doctor → uv sync → build web if stale → migrate/seed/agents → supervisor (detached, or -f).
# Env: HQ_PORT, HQ_ENV_FILE, HQ_DB_PATH, HQ_RUN_DIR, HQ_LOG_DIR, HQ_AGENTS_DIR, HQ_LAN, HQ_SKIP_SYNC=1,
#      HQ_SKIP_WEB_BUILD=1 (useful for test runs that must not touch web/ or the venv).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

FOREGROUND=0
PREPARE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    -f|--foreground) FOREGROUND=1 ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    -h|--help) echo "usage: ./start.sh [-f] [--prepare-only]   (-f: supervisor in the foreground; --prepare-only: doctor, deps, web build and database, then exit)"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

ENV_FILE="${HQ_ENV_FILE:-$ROOT/.env}"
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | tr -d "\"'" || true; }
PORT="${HQ_PORT:-$(env_get HQ_PORT)}"
PORT="${PORT:-8765}"
RUN_DIR="${HQ_RUN_DIR:-$ROOT/data/run}"
LOG_DIR="${HQ_LOG_DIR:-$ROOT/data/logs}"
PY="$ROOT/.venv/bin/python"

if [ -t 1 ]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; D=$'\e[2m'; N=$'\e[0m'; else G=""; Y=""; R=""; D=""; N=""; fi
ok()   { echo "${G}✓${N} $*"; }
warn() { echo "${Y}!${N} $*"; }
fail() { echo "${R}✗${N} $*" >&2; exit 1; }

echo "${D}Agent HQ doctor${N}"
command -v uv >/dev/null 2>&1 && ok "uv $(uv --version 2>/dev/null | awk '{print $2}')" || fail "uv not found (brew install uv)"
if command -v node >/dev/null 2>&1; then ok "node $(node --version)"; else warn "node not found — the web UI can't be built"; fi
if [ -d "/Applications/Google Chrome.app" ]; then ok "Google Chrome"; else warn "Google Chrome not found — résumé PDFs need it (phase c)"; fi
if [ -n "$(env_get HQ_XAI_API_KEY)" ]; then ok "Grok (xAI) key in .env"; else warn "no HQ_XAI_API_KEY in .env — HQ runs on local models only until you add one"; fi
if curl -fsS -m 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || curl -fsS -m 2 http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then ok "local model server answering (Ollama / LM Studio)"; else warn "no Ollama / LM Studio answering — run 'make models' to install Ollama and the recommended local models (MLX models are started by HQ)"; fi

if [ -f "$RUN_DIR/supervisor.pid" ] && kill -0 "$(cat "$RUN_DIR/supervisor.pid")" 2>/dev/null; then
  ok "already running (supervisor pid $(cat "$RUN_DIR/supervisor.pid"))"
  echo "Agent HQ → http://localhost:$PORT"
  exit 0
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "port $PORT is already in use ($(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | awk 'NR==2{print $1" pid "$2}')) — if that is a leftover Agent HQ, run ./stop.sh; or pick another HQ_PORT"
fi
ok "port $PORT free"
avail_kb=$(df -Pk "$ROOT" | awk 'NR==2{print $4}')
if [ "${avail_kb:-0}" -lt 1048576 ]; then warn "less than 1 GB of free disk"; else ok "disk $((avail_kb / 1048576)) GB free"; fi

if [ "${HQ_SKIP_SYNC:-0}" != "1" ]; then
  uv sync --quiet || fail "uv sync failed"
  ok "python deps in sync"
fi
[ -x "$PY" ] || fail "$PY missing — run uv sync"

if [ "${HQ_SKIP_WEB_BUILD:-0}" != "1" ] && [ -f web/package.json ]; then
  stale=""
  if [ ! -f web/dist/index.html ]; then
    stale="no build yet"
  elif [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit 2>/dev/null)" ]; then
    stale="sources changed"
  fi
  if [ -n "$stale" ]; then
    echo "building web UI ($stale)…"
    if ( cd web && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build ); then
      ok "web UI built"
    else
      warn "web build failed — the API will serve a placeholder page"
    fi
  else
    ok "web UI up to date"
  fi
fi

summary="$("$PY" -m hq.util.bootstrap)" || fail "database setup failed (migrate/seed/agents) — see the error above"
ok "$summary"

mkdir -p "$RUN_DIR" "$LOG_DIR"
[ "$PREPARE_ONLY" = "1" ] && exit 0
PLIST="$HOME/Library/LaunchAgents/com.prerit.agenthq.plist"
if [ "$FOREGROUND" = "0" ] && [ "$(uname)" = "Darwin" ] && [ -f "$PLIST" ]; then
  # installed as a LaunchAgent: let launchd own the process so it is restarted and survives logout/login
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl kickstart -k "gui/$(id -u)/com.prerit.agenthq"
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && { ok "running under launchd"; echo "Agent HQ → http://localhost:$PORT"; exit 0; }
    sleep 0.5
  done
  fail "API did not answer within 30 s — see $LOG_DIR/launchd.err.log and $LOG_DIR/supervisor.log"
fi
if [ "$FOREGROUND" = "1" ]; then
  echo "Agent HQ → http://localhost:$PORT  (foreground; Ctrl-C to stop)"
  exec "$PY" -m hq.supervisor
fi

nohup "$PY" -m hq.supervisor >>"$LOG_DIR/supervisor.log" 2>&1 &
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    ok "supervisor pid $(cat "$RUN_DIR/supervisor.pid" 2>/dev/null || echo '?') · logs in $LOG_DIR"
    echo "Agent HQ → http://localhost:$PORT"
    exit 0
  fi
  sleep 0.5
done
fail "API did not answer within 30 s — see $LOG_DIR/api.log and $LOG_DIR/supervisor.log"
