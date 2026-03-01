# vault-ddapi

Sync Veeva Vault data to a local SQLite database using the [Vault Direct Data API](https://developer.veevavault.com/directdata/).

Designed to run as a macOS cron job, keeping the database continuously up to date for querying by other scripts.

> **Part of the `vault-tools` package.** Install from the root — no separate install needed.

---

## What it syncs

| Data | Notes |
|------|-------|
| Documents & Document Versions | Core metadata only (no binaries) |
| Users & Groups | Includes group membership |
| Custom Vault Objects | All objects — auto-discovered from manifest |
| Audit Trail | Domain audit trail if available |

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- A Veeva Vault account with Direct Data API access

---

## Install

Install from the **vault-tools root**:

```bash
cd /path/to/vault-tools
uv sync
```

This registers the `vault-ddapi` command globally.

Then add the vault-ddapi keys to the **root** `vault-tools/.env`:

```dotenv
# vault-ddapi settings — add to vault-tools/.env
DB_PATH=/absolute/path/to/vault.db
LOG_PATH=/absolute/path/to/logs/vault-ddapi.log
WORK_DIR=/absolute/path/to/tmp/ddapi-work
```

Use **absolute paths** for all three — required for cron/launchd to work correctly.
See [.env.example](.env.example) for all available options.

---

## Usage

### One-off sync

```bash
# Auto-detects full seed vs incremental
vault-ddapi sync

# Force a full re-seed (overwrites existing data)
vault-ddapi sync --full
```

### Status

```bash
vault-ddapi status
```

Prints the last sync timestamps and row counts for every table.

---

## Automated sync (every 15 minutes)

### Option A — macOS launchd (recommended)

1. Edit `com.vault-ddapi.sync.plist` — replace both `REPLACE_WITH_ABSOLUTE_PATH` placeholders with the absolute path to the vault-tools root.

2. Copy the plist to your LaunchAgents folder:

   ```bash
   cp vault-ddapi/com.vault-ddapi.sync.plist ~/Library/LaunchAgents/
   ```

3. Load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.vault-ddapi.sync.plist
   ```

4. Verify it's running:

   ```bash
   launchctl list | grep vault-ddapi
   ```

To stop and remove:

```bash
launchctl unload ~/Library/LaunchAgents/com.vault-ddapi.sync.plist
rm ~/Library/LaunchAgents/com.vault-ddapi.sync.plist
```

### Option B — crontab

```bash
crontab -e
```

Add (replace `/absolute/path/to/vault-tools`):

```
*/15 * * * * /absolute/path/to/vault-tools/vault-ddapi/run_sync.sh >> /absolute/path/to/vault-tools/vault-ddapi/logs/cron.log 2>&1
```

---

## Querying the database

The SQLite database at `DB_PATH` uses [WAL mode](https://www.sqlite.org/wal.html), so you can read it safely while a sync is in progress.

```python
import sqlite3

con = sqlite3.connect("/absolute/path/to/vault.db")
con.row_factory = sqlite3.Row

# Example: find documents by name
rows = con.execute("SELECT id, name, status FROM documents WHERE name LIKE '%Protocol%'").fetchall()
for row in rows:
    print(dict(row))

con.close()
```

Table names mirror Vault object/field labels where available, otherwise field names are used as-is. See `_sync_meta` for last sync timestamps.

---

## Logs

| File | Contents |
|------|----------|
| `LOG_PATH` (set in `.env`) | Rotating application log (10 MB × 5 files) |
| `vault-ddapi/logs/cron.log` | stdout/stderr from cron runs |
| `vault-ddapi/logs/launchd.log` | stdout from launchd runs |
| `vault-ddapi/logs/launchd-error.log` | stderr from launchd runs |

---

## Configuration reference (root `vault-tools/.env`)

All settings live in the shared root `.env`. Vault connection keys are already present; add the vault-ddapi-specific ones.

| Variable | Required | Description |
|----------|----------|-------------|
| `VAULT_URL` | Yes | Full Vault URL, e.g. `https://myco.veevavault.com` |
| `VAULT_USERNAME` | Yes | Vault login email |
| `VAULT_PASSWORD` | Yes | Vault password |
| `VAULT_VERSION` | No | API version, e.g. `v25.3` — defaults to `v24.1` |
| `DB_PATH` | Yes | Absolute path to the SQLite file |
| `LOG_PATH` | Yes | Absolute path to the log file |
| `WORK_DIR` | Yes | Absolute path to scratch directory for downloads |
| `EXTRACT_TYPE` | No | `incremental` (default) or `full` to force a full seed |
| `MAX_RETRIES` | No | API retry attempts, default `3` |
| `RETRY_BACKOFF_SECONDS` | No | Initial retry delay in seconds, default `5` (doubles each retry) |

---

## How it works

```
vault-ddapi sync
      │
      ├─ DB exists? ──NO──▶ Full seed
      │                         download full .tar.gz
      │                         extract archive
      │                         create tables from manifest
      │                         load all rows
      │                         record timestamp
      │
      └─ YES ──▶ Incremental sync
                    read last_inc timestamp
                    download 15-min incremental file
                    extract archive
                    upsert changed rows / apply deletes
                    record timestamp
```

The accelerator library (`veeva/Vault-Direct-Data-API-Accelerators`) handles the low-level Direct Data API calls, multipart downloads, archive extraction, manifest parsing, and SQLite upsert logic. `vault-tools` orchestrates those components and adds `.env` config, retry logic, WAL mode, and cron-friendly entry points.
