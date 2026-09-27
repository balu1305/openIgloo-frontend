#!/usr/bin/env bash
# ==============================================================================
# Ask the Tenant Book — Reindex Script
# Validates and builds index over the specified corpus directory
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

CORPUS_DIR="${1:-corpus}"
echo "Reindexing corpus from ${CORPUS_DIR}..."

python3 -c "
import sys, os
sys.path.insert(0, 'rag_pipeline')
from engine import TenantBookEngine
engine = TenantBookEngine('${CORPUS_DIR}')
print(f'✓ Successfully indexed {len(engine.passages)} passages across {len(engine.manifest)} documents in ${CORPUS_DIR}.')
"
