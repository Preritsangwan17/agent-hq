#!/usr/bin/env bash
# Stop Agent HQ: SIGTERM the supervisor (it drains the worker and stops the API), SIGKILL after 25 s.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${HQ_RUN_DIR:-$ROOT/data/run}"
PIDFILE="$RUN_DIR/supervisor.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "Agent HQ is not running (no $PIDFILE)"
  exit 0
fi
PID="$(cat "$PIDFILE")"
if ! kill -0 "$PID" 2>/dev/null; then
  echo "removing stale pidfile (pid $PID is gone)"
  rm -f "$PIDFILE"
  exit 0
fi
echo "stopping supervisor pid $PID…"
kill -TERM "$PID"
for _ in $(seq 1 100); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "stopped"
    exit 0
  fi
  sleep 0.25
done
echo "supervisor did not stop within 25 s; killing it and its children" >&2
pkill -KILL -P "$PID" 2>/dev/null || true
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PIDFILE"
