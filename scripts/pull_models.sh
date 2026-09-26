#!/usr/bin/env bash
# Download the recommended local models for this Mac (config/local_models.yaml) through Ollama.
#   ./scripts/pull_models.sh            the core set (~39 GB: writer, two independent checkers, a fast small model)
#   ./scripts/pull_models.sh --all      core + optional (~105 GB in total)
#   ./scripts/pull_models.sh qwen3:4b   just the named models
# Installs and starts Ollama with Homebrew if it's missing. Safe to run again: finished models are skipped.
# HQ notices new models within 10 minutes (or click Rescan on the Models page), benchmarks them and assigns roles.
set -euo pipefail
cd "$(dirname "$0")/.."
say() { printf "\n\033[1m==> %s\033[0m\n" "$*"; }

if ! command -v ollama >/dev/null 2>&1; then
  command -v brew >/dev/null 2>&1 || { echo "Install Homebrew first (https://brew.sh), then run this again."; exit 1; }
  say "Installing Ollama"
  brew install ollama
fi
if ! curl -fsS -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  say "Starting Ollama (it keeps running in the background and after login)"
  brew services start ollama >/dev/null 2>&1 || (nohup ollama serve >/dev/null 2>&1 &)
  for _ in $(seq 1 20); do curl -fsS -m 1 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
fi

if [ "$#" -gt 0 ] && [ "$1" != "--all" ]; then
  models=("$@")
else
  set_filter="core"; [ "${1:-}" = "--all" ] && set_filter="all"
  models=()
  while IFS= read -r line; do models+=("$line"); done < <(python3 - "$set_filter" <<'PY'
import re, sys
want = sys.argv[1]
for line in open("config/local_models.yaml"):
    m = re.search(r'ollama:\s*"([^"]+)".*set:\s*(\w+)', line)
    if m and (want == "all" or m.group(2) == want):
        print(m.group(1))
PY
)
fi

free_gb=$(df -g "$HOME" | awk 'NR==2 {print $4}')
say "Free disk: ${free_gb} GB. Downloading: ${models[*]}"
for m in "${models[@]}"; do
  say "ollama pull $m"
  ollama pull "$m"
done
say "Done. Open Agent HQ › Models and click Rescan (or wait up to 10 minutes); HQ benchmarks the new models and assigns roles."
