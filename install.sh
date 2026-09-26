#!/usr/bin/env bash
# One-line installer for macOS:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/Preritsangwan17/agent-hq/main/install.sh)"
# Installs Homebrew (if missing), uv, node and git; downloads (or updates) Agent HQ into ~/agent-hq; starts it and
# opens Safari at http://localhost:8765. Safe to run again: it only updates and restarts.
set -euo pipefail
REPO="https://github.com/Preritsangwan17/agent-hq.git"
DIR="${AGENT_HQ_DIR:-$HOME/agent-hq}"

say() { printf "\n\033[1m==> %s\033[0m\n" "$*"; }
[ "$(uname)" = "Darwin" ] || { echo "This installer is for macOS."; exit 1; }

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew (it will ask for your Mac password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
  # make brew available in future Terminal windows
  grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo "eval \"\$($(command -v brew) shellenv)\"" >> "$HOME/.zprofile"
fi

say "Installing uv, node and git"
brew install uv node git >/dev/null || brew install uv node git

if [ -d "$DIR/.git" ]; then
  say "Updating Agent HQ in $DIR"
  git -C "$DIR" pull --ff-only
else
  say "Downloading Agent HQ into $DIR"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
chmod +x start.sh stop.sh scripts/*.sh 2>/dev/null || true
say "Starting Agent HQ (the first run installs packages and takes a few minutes)"
./stop.sh >/dev/null 2>&1 || true
./start.sh

open -a Safari "http://localhost:8765" 2>/dev/null || open "http://localhost:8765"
cat <<'MSG'

Agent HQ is running → http://localhost:8765 (Safari just opened it).
  • First visit: choose a passcode.
  • Settings › Simulation: turn it off to see only real jobs.
  • Add your xAI key:   echo 'HQ_XAI_API_KEY=your-key' >> ~/agent-hq/.env
  • Start automatically after login:   cd ~/agent-hq && make install-launchd
  • Stop / start later:   cd ~/agent-hq && make down   /   make up
MSG
