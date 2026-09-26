#!/usr/bin/env bash
# Remove the Agent HQ LaunchAgent (stops Agent HQ; start it by hand with make up afterwards).
set -euo pipefail
LABEL="com.prerit.agenthq"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "✓ LaunchAgent removed. Start Agent HQ by hand with: make up"
