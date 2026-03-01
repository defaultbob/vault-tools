# vault-tools Memory

## Versioning rule
For every uv-installable project in this repo, increment `pyproject.toml` version on every change:
- **Patch** (x.x.1) for bug fixes
- **Minor** (x.1.0) for new features
- **Major** (1.0.0) for breaking changes
Write/update the project's `CHANGELOG.md` to match every time.

## Package structure
Single installable `vault-tools` package. Sub-tools live as subpackages of `vault_tools/`.
Their config/cron helpers live in named subdirs (e.g. `ddapi-local/`) but code is under `vault_tools/`.

- `vault-tools/` — root package (`pyproject.toml` v1.1.0)
  - CLI: `vault-log-analyzer` → `vault_tools.log_analyzer:main`
  - CLI: `vault-ddapi` → `vault_tools.ddapi_local.cli:main`
- `vault-tools/vault-ddapi/` — cron helpers, README, SPEC, plist (NOT a separate package)
- Code: `vault_tools/ddapi_local/` — subpackage within root

## vault-ddapi architecture
- Thin orchestration layer over `veeva/Vault-Direct-Data-API-Accelerators` (Git dep)
- Reads from root `vault-tools/.env` (keys: `VAULT_URL`, `VAULT_USERNAME`, `VAULT_PASSWORD`, `VAULT_VERSION`)
- ddapi-specific keys in same root `.env`: `DB_PATH`, `LOG_PATH`, `WORK_DIR`
- `_PROJECT_ROOT` in config.py: `Path(__file__).resolve().parent.parent.parent` (3 levels up from `vault_tools/ddapi_local/`)
- SQLite in WAL mode; `_sync_meta` table tracks last full/incremental timestamps
- Retry with exponential backoff on all Vault API calls
