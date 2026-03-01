# Changelog — vault-tools

All notable changes are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

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
