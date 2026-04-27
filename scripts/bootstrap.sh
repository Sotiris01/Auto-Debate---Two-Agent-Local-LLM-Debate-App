#!/usr/bin/env bash
# scripts/bootstrap.sh — POSIX wrapper for bootstrap_env.py
#
# Usage:
#   ./scripts/bootstrap.sh              # runtime deps only
#   ./scripts/bootstrap.sh --dev        # also install dev deps
#   ./scripts/bootstrap.sh --recreate   # nuke .venv and start fresh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3.10+ not found on PATH. Install from https://www.python.org/downloads/" >&2
    exit 1
fi

exec "$PY" scripts/bootstrap_env.py "$@"
