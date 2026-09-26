#!/usr/bin/env bash
# Stop Agent HQ: SIGTERM the supervisor (it drains the worker and stops the API), SIGKILL after 25 s.
# Also reaps an API/worker left behind by a supervisor that died without cleaning up (kill -9, crash): their pids
# are in $RUN_DIR/{api,worker}.pid and are only signalled if that pid is still running `-m hq.api` / `-m hq.worker`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${HQ_RUN_DIR:-$ROOT/data/run}"
PIDFILE="$RUN_DIR/supervisor.pid"

wait_gone() {  # wait_gone <pid> <seconds>
  local i
  for i in $(seq 1 $(($2 * 4))); do
    kill -0 "$1" 2>/dev/null || return 0
    sleep 0.25
  done
  ! kill -0 "$1" 2>/dev/null
}

reaped=0
reap_children() {
  local name pidfile pid cmd
  for name in api worker; do
    pidfile="$RUN_DIR/$name.pid"
    [ -f "$pidfile" ] || continue
    pid="$(tr -dc '0-9' <"$pidfile")"
    cmd=""
    [ -n "$pid" ] && cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$cmd" == *"-m hq.$name"* ]]; then
      echo "stopping leftover $name pid $pid…"
      kill -TERM "$pid" 2>/dev/null || true
      wait_gone "$pid" 10 || { echo "$name pid $pid ignored SIGTERM; killing it" >&2; kill -KILL "$pid" 2>/dev/null || true; }
      reaped=1
    fi
    rm -f "$pidfile"
  done
}

if [ ! -f "$PIDFILE" ]; then
  reap_children
  [ "$reaped" = 1 ] && echo "stopped" || echo "Agent HQ is not running (no $PIDFILE)"
  exit 0
fi
PID="$(tr -dc '0-9' <"$PIDFILE")"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "removing stale pidfile (supervisor pid ${PID:-?} is gone)"
  rm -f "$PIDFILE"
  reap_children
  exit 0
fi
echo "stopping supervisor pid $PID…"
kill -TERM "$PID"
if wait_gone "$PID" 25; then
  reap_children
  echo "stopped"
  exit 0
fi
echo "supervisor did not stop within 25 s; killing it and its children" >&2
pkill -KILL -P "$PID" 2>/dev/null || true
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PIDFILE"
reap_children
