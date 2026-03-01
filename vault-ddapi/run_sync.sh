#!/usr/bin/env bash
# run_sync.sh — Shell wrapper for running vault-ddapi from cron / launchd.
#
# Usage:
#   ./run_sync.sh           # incremental sync
#   ./run_sync.sh --full    # force full seed
#
# Recommended cron entry (every 15 minutes):
#   */15 * * * * /absolute/path/to/vault-tools/vault-ddapi/run_sync.sh >> /absolute/path/to/vault-tools/vault-ddapi/logs/cron.log 2>&1

set -euo pipefail

# Activate the vault-tools root venv (one level up from this script)
VAULT_TOOLS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$VAULT_TOOLS_ROOT/.venv/bin/activate"

# Run the sync, forwarding any extra arguments (e.g. --full)
vault-ddapi sync "$@"
