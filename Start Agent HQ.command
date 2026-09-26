#!/usr/bin/env bash
# Double-click me in Finder. First time: right-click → Open → Open (macOS asks because the file was downloaded).
# Installs what's missing (Homebrew, uv, node), starts Agent HQ from this folder and opens Safari.
cd "$(dirname "$0")" || exit 1
set -e
say() { printf "\n\033[1m==> %s\033[0m\n" "$*"; }

for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew — type your Mac password when asked (nothing shows while you type)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
  grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo "eval \"\$($(command -v brew) shellenv)\"" >> "$HOME/.zprofile"
fi
for tool in uv node; do
  command -v "$tool" >/dev/null 2>&1 || { say "Installing $tool"; brew install "$tool"; }
done

chmod +x start.sh stop.sh scripts/*.sh 2>/dev/null || true
say "Starting Agent HQ (the first time takes a few minutes)"
./start.sh
open -a Safari "http://localhost:8765" 2>/dev/null || open "http://localhost:8765"
say "Done. Agent HQ is open in Safari: http://localhost:8765  — you can close this window."
