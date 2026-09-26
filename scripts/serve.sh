#!/usr/bin/env bash
# ==============================================================================
# Ask the Tenant Book — Server Launcher Script
# Starts the zero-dependency standard library Python server.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

echo "================================================================="
echo " Starting 'Ask the Tenant Book' (openigloo Assistant) UI"
echo " Host: http://${HOST}:${PORT}"
echo " Root: ${REPO_DIR}"
echo "================================================================="

cd "${REPO_DIR}"
exec python3 app/server.py --port "${PORT}" --host "${HOST}"
