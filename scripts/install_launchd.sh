#!/usr/bin/env bash
# Install Agent HQ as a LaunchAgent (com.prerit.agenthq): starts after you log in, restarts if it dies
# (KeepAlive, ThrottleInterval 30), logs in data/logs. With FileVault on, nothing runs after a reboot until you log
# in — that is expected; don't turn FileVault off for this. Undo with scripts/uninstall_launchd.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.prerit.agenthq"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$ROOT/data/logs"
PORT="$(sed -n 's/^HQ_PORT=//p' "$ROOT/.env" 2>/dev/null | tail -1)"; PORT="${PORT:-8765}"
[ "$(uname)" = "Darwin" ] || { echo "launchd is macOS only" >&2; exit 1; }

echo "1/4 stopping any running copy…"
"$ROOT/stop.sh" >/dev/null 2>&1 || true
echo "2/4 preparing (doctor, deps, web build, database)…"
"$ROOT/start.sh" --prepare-only

echo "3/4 writing $PLIST"
mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
cat >"$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/.venv/bin/python</string><string>-m</string><string>hq.supervisor</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>$HOME</string>
    <key>PYTHONUTF8</key><string>1</string>
  </dict>
  <key>StandardOutPath</key><string>$LOG_DIR/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/launchd.err.log</string>
</dict>
</plist>
PL
plutil -lint "$PLIST" >/dev/null

echo "4/4 loading it…"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "✗ API not answering — see $LOG_DIR/launchd.err.log" >&2; exit 1; }
echo "✓ Agent HQ runs under launchd → http://localhost:$PORT"

echo "checking what works from the launchd context (≈20 s)…"
"$ROOT/.venv/bin/python" - <<'PY'
import time
from hq import settings
settings.load_env()
from hq.db.conn import connect, tx
from hq.db.seed import get_setting
from hq import notify
conn = connect()
with tx(conn):
    nid = notify.create(conn, "warn", "Agent HQ is installed", "This banner shows notifications work from launchd.")
state = None
for _ in range(40):
    state = conn.execute("SELECT mac_delivered FROM notifications WHERE id=?", (nid,)).fetchone()[0]
    if state != 0:
        break
    time.sleep(0.5)
print("✓ macOS notifications work" if state == 1 else
      "! macOS notification not shown — allow notifications for 'Script Editor' / terminal-notifier in System Settings › Notifications")
cloud = get_setting(conn, "claude_state") or {}
print(f"✓ cloud model reachable ({cloud.get('provider')})" if cloud.get("available") else
      f"! cloud model not reachable yet: {cloud.get('reason') or 'not checked yet'} (add HQ_XAI_API_KEY to .env or run `claude auth login`)")
PY
