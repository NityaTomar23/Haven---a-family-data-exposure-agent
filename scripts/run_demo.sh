#!/usr/bin/env bash
set -euo pipefail

# One-command local launcher for Haven.
# Uses uv if installed, otherwise falls back to active python.

export HAVEN_PROVIDER_MODE="${HAVEN_PROVIDER_MODE:-auto}"
export HAVEN_SCAN_RATE_LIMIT="${HAVEN_SCAN_RATE_LIMIT:-10}"
export HAVEN_HOST="${HAVEN_HOST:-127.0.0.1}"
export HAVEN_PORT="${HAVEN_PORT:-8000}"

echo "Starting Haven dashboard on http://${HAVEN_HOST}:${HAVEN_PORT} (provider_mode=${HAVEN_PROVIDER_MODE}, rate_limit=${HAVEN_SCAN_RATE_LIMIT}/hr)"

if command -v uv >/dev/null 2>&1; then
  exec uv run python scripts/serve.py
else
  exec python scripts/serve.py
fi

