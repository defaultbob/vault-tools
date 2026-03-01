# Changelog — vault-tools

All notable changes are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.2.1] — 2026-03-01

### Fixed
- Manifest processing rewritten to match actual Vault archive format:
  - Columns are `extract`, `extract_label`, `type`, `records`, `file` (not `filename`)
  - Table name derived from `extract` field (e.g. `Object.activity__v` → `Object_activity__v`)
  - `type=deletes` rows now correctly delete rows by `id` before any inserts
  - Rows with empty `file` or `records=0` are skipped without error
- `delete-then-insert` applied on all `updates` rows (handles both new records and changed records correctly)

---

## [1.2.0] — 2026-03-01

### Changed
- Full seed now catches up: after applying the most recent full extract it applies all incrementals generated since that full's `stop_time`, in chronological order
- Incremental sync applies each available extract individually in order rather than batching them; `last_inc` in `_sync_meta` is updated after each one so a mid-run failure resumes from where it left off
- `last_full` / `last_inc` now store the Vault extract's `stop_time` (not wall-clock time), making them exact resume points for the next query

---

## [1.1.8] — 2026-03-01

### Fixed
- Vault part files are named `*.tar.gz.001` (not `*.tar.gz`) — extraction now strips the `.NNN` suffix and opens part files directly as gzip streams; multi-part archives are concatenated via a streaming reader before extraction

---

## [1.1.7] — 2026-03-01

### Fixed
- Corrected all API calls against the Vault API v25.3 spec:
  - `extract_type` query param now uses correct values (`full_directdata`, `incremental_directdata`) — server-side filtering, no longer fetching all 947 files for every sync
  - `start_time` / `stop_time` query params sent on incremental list requests so the server returns only the relevant window
  - `X-VaultAPI-ClientID: vault-tools-ddapi` header added to all requests (appears in Vault API Usage Logs)
  - Incremental upsert now matches on `"incremental" in extract_type` to handle the `incremental_directdata` suffix correctly

---

## [1.1.6] — 2026-03-01

### Fixed
- Direct Data API does not accept an `extract_type` query parameter — it returns all files and the type is a field on each item (`full_directdata` / `incremental_directdata`). Now fetches the full catalogue and filters client-side: full sync picks the most-recent `full_directdata` entry; incremental picks all `incremental_directdata` entries with `start_time >= last_sync`, sorted oldest-first

---

## [1.1.5] — 2026-03-01

### Fixed
- `extract_type` sent to Vault API is now uppercased (`FULL`, `INCREMENTAL`) — API rejects lowercase values with `INVALID_DATA`
- Full API response body (pretty-printed JSON) is now logged at ERROR level on any auth or list failure, making future API errors self-diagnosing

---

## [1.1.4] — 2026-03-01

### Fixed
- Replaced all imports of `common.services` and `accelerators.*` (not shipped in the accelerator wheel) with a self-contained implementation using `requests` directly
- `vault-ddapi sync` now: authenticates via POST `/api/{version}/auth`, lists Direct Data files, streams downloads, extracts tar.gz, and loads CSV/Parquet into SQLite — no dependency on accelerator scripts that aren't installed
- Removed now-unused `write_accelerator_configs`, `vapil_settings_path`, `connector_config_path` from `config.py`

---

## [1.1.3] — 2026-03-01

### Fixed
- `vault-ddapi` now resolves `.env` by searching up from the current working directory (same as `vault-log-analyzer`), instead of hardcoding the path relative to the installed package location — fixes "Missing required .env variables" error when installed via `uv tool install`

---

## [1.1.2] — 2026-03-01

### Fixed
- Removed explicit `pandas` and `pyarrow` deps — they are pinned by the accelerator (`pandas~=2.2.3`, `pyarrow~=19.0.0`) and pulled in transitively; our looser pins were causing source builds on Python 3.14 (no wheels available, requires cmake)
- Capped `requires-python` to `<3.14` to prevent installation on Python versions with no pre-built wheels for key dependencies

---

## [1.1.1] — 2026-03-01

### Fixed
- Removed nonexistent `vapil` Python dependency (VAPIL is Java-only; the accelerator package is self-contained)
- Corrected accelerator package name to `vault-direct-data-api-accelerators` (matching its own `pyproject.toml`)
- Added `tool.hatch.metadata.allow-direct-references = true` so hatchling accepts the git dependency

---

## [1.1.0] — 2026-03-01

### Added
- `vault-ddapi` command — sync Veeva Vault data to a local SQLite database via Direct Data API
  - `vault-ddapi sync` — auto-detects full seed vs 15-minute incremental sync
  - `vault-ddapi sync --full` — force a full re-seed
  - `vault-ddapi status` — show last sync timestamps and per-table row counts
  - SQLite WAL mode for safe concurrent reads during sync
  - Exponential-backoff retry on all Vault API calls
  - Rotating file logger (10 MB × 5 backups)
  - cron/launchd helpers in `vault-ddapi/`
- New dependencies: `pandas`, `pyarrow`, `vault-direct-data-api-accelerators`

### Changed
- `requires-python` bumped to `>=3.11` (required by ddapi dependencies)

---

## [1.0.0] — initial release

### Added
- `vault-log-analyzer` command
