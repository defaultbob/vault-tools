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

# cd to project root so find_dotenv can locate .env
VAULT_TOOLS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$VAULT_TOOLS_ROOT"

# vault-ddapi is installed as a uv tool — use its absolute path so launchd
# doesn't need PATH to be set correctly
exec "$HOME/.local/bin/vault-ddapi" sync "$@"
