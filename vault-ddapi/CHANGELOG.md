# Changelog — vault-ddapi

Changes here track the `vault-ddapi` command, which ships as part of `vault-tools`.
See the [root CHANGELOG](../CHANGELOG.md) for full release notes.

---

## vault-tools [1.1.0] — 2026-03-01

### Added
- Initial release of `vault-ddapi` (previously prototyped as standalone `vault-ddapi`)
- Folded into root `vault-tools` package as `vault_tools.ddapi_local` subpackage
- `vault-ddapi sync` — auto-detects full seed vs 15-minute incremental sync
- `vault-ddapi sync --full` — force a full re-seed
- `vault-ddapi status` — last sync timestamps and per-table row counts
- SQLite WAL mode for safe concurrent reads during sync
- `_sync_meta` table tracks last full/incremental timestamps
- Exponential-backoff retry on all Vault API calls (`MAX_RETRIES`, `RETRY_BACKOFF_SECONDS`)
- Reads from root `vault-tools/.env`
- Runtime generation of accelerator JSON configs
- Rotating file logger (10 MB × 5 backups)
- `run_sync.sh` cron/launchd wrapper (activates root `.venv`)
- `com.vault-ddapi.sync.plist` macOS launchd plist (15-minute interval)
- `SPEC.md` specification document
