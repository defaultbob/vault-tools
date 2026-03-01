# vault-ddapi — Specification

**Version:** 1.0
**Date:** 2026-03-01
**Status:** Approved

---

## 1. Overview

`vault-ddapi` is a Python CLI tool that syncs data from a Veeva Vault instance to a local SQLite database using the Vault Direct Data API (v24+). It is designed to run as a macOS cron job, keeping the local database continuously up to date for use by other scripts and tools.

---

## 2. Goals

| Goal | Detail |
|------|--------|
| Full seed | On first run (no DB detected), download and load the latest Full extract |
| Incremental sync | On subsequent runs, download and apply 15-minute Incremental files |
| Live DB | The SQLite database remains queryable throughout all operations |
| Cron-safe | Idempotent, self-contained, safe to run every 15 minutes via `launchd`/`cron` |
| Queryable schema | Stable, documented table structure for use by external scripts |
| Observability | Structured log file for debugging |

---

## 3. Data Scope

The following Vault data types are synced:

| Category | Vault Object Types |
|----------|--------------------|
| Documents | `documents`, `document_versions` |
| Users & Groups | `users`, `groups`, `group_membership` |
| Custom Objects | All custom Vault objects — auto-discovered via manifest |
| Audit Trail | `audit_trail`, `domain_audit_trail` (if available) |

All objects present in the Direct Data extract manifest are processed. There is no whitelist/blacklist — the manifest drives what is synced.

---

## 4. Architecture

```
vault-ddapi/
├── pyproject.toml          # uv/pip project definition
├── .env.example            # Credential/config template
├── README.md               # Install and usage guide
├── run_sync.sh             # Simple shell wrapper for cron
│
└── src/
    └── ddapi_local/
        ├── __init__.py
        ├── cli.py              # Entry point: `vault-ddapi sync`
        ├── config.py           # .env loader and validation
        ├── logger.py           # Rotating file logger setup
        ├── sync.py             # Orchestration: full vs incremental
        ├── db.py               # SQLite wrapper (WAL mode, schema helpers)
        └── vault.py            # Thin wrapper around VaultService + scripts
```

The tool is a **thin orchestration layer** on top of the upstream `vault-direct-data-api-accelerators` package. It does not re-implement download, extraction, or CSV loading — it imports and drives those components.

---

## 5. Dependency on Accelerator Package

The upstream repository (`veeva/Vault-Direct-Data-API-Accelerators`) is installed as a Git dependency:

```toml
# pyproject.toml
[tool.uv.sources]
vault-direct-data-accelerators = { git = "https://github.com/veeva/Vault-Direct-Data-API-Accelerators" }
```

Modules used:
- `common.services.vault_service.VaultService` — auth + Direct Data file listing/download
- `accelerators.sqlite.services.sqlite_service.SqliteService` — schema management + data loading
- `accelerators.sqlite.scripts.download_direct_data_file` — `.tar.gz` download (multipart-aware)
- `accelerators.sqlite.scripts.unzip_direct_data_file` — archive extraction
- `accelerators.sqlite.scripts.load_data` — manifest-driven table creation + row loading
- `common.utilities.read_json_file`, `log_message` — shared helpers

---

## 6. Configuration

### 6.1 Credentials & paths — root `vault-tools/.env`

Settings are read from the shared root `.env` (gitignored), the same file used by all other vault-tools scripts. The path is overridable via the `DDAPI_ENV_FILE` env var.

```dotenv
# Vault connection — already present in root .env
VAULT_URL=https://your-vault.veevavault.com
VAULT_USERNAME=your@email.com
VAULT_PASSWORD=your_password
VAULT_VERSION=v25.3              # optional, defaults to v24.1

# vault-ddapi specific — add these to root .env
# Use absolute paths (required for cron)
DB_PATH=/absolute/path/to/vault.db
LOG_PATH=/absolute/path/to/logs/vault-ddapi.log
WORK_DIR=/absolute/path/to/tmp/ddapi-work

# Sync behaviour
EXTRACT_TYPE=incremental         # 'full' forces a full seed regardless of DB state
MAX_RETRIES=3
RETRY_BACKOFF_SECONDS=5
```

### 6.2 Derived config files

The config layer auto-generates the JSON files expected by the accelerator (`vapil_settings.json`, `connector_config.json`) in `WORK_DIR` at runtime — the user never touches them directly.

---

## 7. CLI Interface

Entry point: `vault-ddapi`

```
Usage:
  vault-ddapi sync [--full]   Run a sync (auto-detects full vs incremental)
  vault-ddapi status          Show last sync time, DB row counts per table
  vault-ddapi --help
```

`--full` flag: forces a Full extract even if a DB already exists (useful for resets).

---

## 8. Sync Logic

### 8.1 Decision tree

```
Start
 │
 ├─ DB file exists AND EXTRACT_TYPE != 'full'?
 │    └─ YES → Incremental sync
 │    └─ NO  → Full seed
```

### 8.2 Full seed

1. Create `WORK_DIR` if needed.
2. Generate `vapil_settings.json` and `connector_config.json` in `WORK_DIR`.
3. Call `download_direct_data_file.run()` with `extract_type=full`.
4. Call `unzip_direct_data_file.run()`.
5. Open SQLite in WAL mode.
6. Call `load_data.run()` — creates all tables from manifest metadata.
7. Record sync timestamp in `_sync_meta` table.
8. Log success.

### 8.3 Incremental sync

1. Read last sync timestamp from `_sync_meta`.
2. Generate config with `extract_type=incremental`, `start_time=last_sync`, `stop_time=now`.
3. Call `download_direct_data_file.run()`.
   - If no incremental files available yet: log and exit cleanly (next cron run will catch up).
4. Call `unzip_direct_data_file.run()`.
5. Call `load_data.run()` — applies upserts and deletes via staging tables.
6. Update `_sync_meta`.
7. Log success.

### 8.4 Retry policy

Any step that calls the Vault API is wrapped in a retry loop:
- Up to `MAX_RETRIES` attempts (default 3).
- Exponential backoff starting at `RETRY_BACKOFF_SECONDS` (default 5s): 5s → 10s → 20s.
- On final failure: log the exception at ERROR level and continue to the next step/run.
- The DB is never left in a partial state — WAL mode ensures readers are unaffected.

---

## 9. Database Schema

### 9.1 WAL mode

The DB is always opened with `PRAGMA journal_mode=WAL` so external readers (other scripts) can query it while a write is in progress.

### 9.2 Column naming

- If the Vault metadata CSV includes a `label` column for a field, the SQLite column name is derived from that label (lowercased, spaces→underscores, special chars stripped).
- Otherwise the Vault field name is used as-is.

### 9.3 Sync metadata table

```sql
CREATE TABLE IF NOT EXISTS _sync_meta (
    id          INTEGER PRIMARY KEY,
    last_full   TEXT,   -- ISO-8601 UTC timestamp of last full seed
    last_inc    TEXT,   -- ISO-8601 UTC timestamp of last incremental
    db_version  TEXT    -- accelerator schema version
);
```

### 9.4 Stable table inventory (seeded on full sync)

| Table name pattern | Source |
|--------------------|--------|
| `documents` | Vault Documents |
| `document_versions` | Vault Document Versions |
| `users` | Vault Users |
| `groups` | Vault Groups |
| `group_membership` | Vault Group Membership |
| `audit_trail` | Vault Audit Trail |
| `<object_name>` | Each auto-discovered custom Vault object |

Table names with leading digits are prefixed `n_` (accelerator convention).

---

## 10. Logging

- Library: Python `logging` with `RotatingFileHandler`.
- Log file: `LOG_PATH` from `.env`.
- Rotation: 10 MB per file, 5 backups retained.
- Format: `YYYY-MM-DD HH:MM:SS | LEVEL | module | message`
- Levels used: DEBUG (query text), INFO (progress), WARNING (skipped files), ERROR (failures).
- stdout also receives INFO+ for interactive runs.

---

## 11. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| No incremental files available | Log INFO, exit 0 — next run will pick them up |
| API auth failure | Log ERROR, retry with backoff, then log and exit 0 |
| Network timeout / partial download | Log ERROR, retry with backoff, then log and exit 0 |
| Corrupt archive | Log ERROR, delete partial files, exit 0 |
| DB write error | Log ERROR (DB in WAL so readers unaffected), exit 0 |
| Missing .env / required field | Log CRITICAL to stdout, exit 1 immediately |

Exit code 0 on all recoverable errors so cron does not spam alert emails.
Exit code 1 only for configuration errors that require human intervention.

---

## 12. Cron Setup

### 12.1 Shell wrapper `run_sync.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
vault-ddapi sync >> logs/cron.log 2>&1
```

### 12.2 macOS `launchd` plist (preferred over crontab)

Path: `~/Library/LaunchAgents/com.vault-ddapi.sync.plist`

Runs every 15 minutes. Full instructions in `README.md`.

### 12.3 crontab alternative

```
*/15 * * * * /absolute/path/to/run_sync.sh
```

---

## 13. Installation (uv)

```bash
git clone <this-repo>
cd vault-ddapi
cp .env.example .env        # fill in credentials and paths
uv sync                     # installs all dependencies including accelerator
vault-ddapi sync            # first run → full seed
```

---

## 14. Out of Scope

- Document binary content / renditions (only metadata is synced)
- Multi-vault support
- Cloud storage backends (S3, Azure) — local only
- Parquet output
- Web UI or REST API over the local DB
