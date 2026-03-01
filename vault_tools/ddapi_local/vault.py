"""
vault.py — Thin wrapper around the accelerator's VaultService and scripts.

Adds retry-with-backoff around every Vault API call.
"""

import time
from pathlib import Path
from typing import Any

from .config import Config
from .logger import get_logger

log = get_logger()


def _with_retry(fn, config: Config, label: str) -> Any:
    """Call fn(), retrying up to config.max_retries times with exponential backoff."""
    delay = config.retry_backoff_seconds
    for attempt in range(1, config.max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == config.max_retries:
                log.error(
                    "%s failed after %d attempts: %s",
                    label,
                    config.max_retries,
                    exc,
                    exc_info=True,
                )
                return None
            log.warning(
                "%s attempt %d/%d failed: %s — retrying in %.0fs",
                label,
                attempt,
                config.max_retries,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= 2


def download_direct_data(config: Config, extract_type: str, start_time: str | None, stop_time: str | None) -> bool:
    """Download the Direct Data archive. Returns True on success."""
    from common.services.vault_service import VaultService
    from accelerators.sqlite.scripts import download_direct_data_file

    config.write_accelerator_configs(extract_type, start_time, stop_time)
    acc_config = _load_connector_config(config)
    if acc_config is None:
        return False

    vault_service = _make_vault_service(config)
    if vault_service is None:
        return False

    direct_data_params = acc_config["direct_data"]
    local_params = acc_config["local"]

    def _run():
        download_direct_data_file.run(
            vault_service=vault_service,
            direct_data_params=direct_data_params,
            local_params=local_params,
        )

    result = _with_retry(_run, config, f"download_direct_data ({extract_type})")
    return result is not None or True  # _run returns None on success; None from retry means failure


def extract_archive(config: Config) -> bool:
    """Extract the downloaded .tar.gz archive."""
    from accelerators.sqlite.scripts import unzip_direct_data_file

    acc_config = _load_connector_config(config)
    if acc_config is None:
        return False

    local_params = acc_config["local"]

    def _run():
        unzip_direct_data_file.run(local_params=local_params)

    _with_retry(_run, config, "extract_archive")
    return True


def load_into_db(config: Config, extract_type: str) -> bool:
    """Load extracted data into SQLite."""
    from accelerators.sqlite.services.sqlite_service import SqliteService
    from accelerators.sqlite.scripts import load_data

    acc_config = _load_connector_config(config)
    if acc_config is None:
        return False

    sqlite_service = SqliteService(acc_config["sqlite"])
    direct_data_params = acc_config["direct_data"]
    local_params = acc_config["local"]

    # Ensure WAL mode is set before the accelerator writes
    _prime_wal(config)

    def _run():
        load_data.run(
            direct_data_params=direct_data_params,
            local_params=local_params,
            sqlite_service=sqlite_service,
        )

    _with_retry(_run, config, f"load_into_db ({extract_type})")
    return True


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_vault_service(config: Config):
    from common.services.vault_service import VaultService

    def _auth():
        return VaultService(str(config.vapil_settings_path()))

    return _with_retry(_auth, config, "VaultService.authenticate")


def _load_connector_config(config: Config) -> dict | None:
    from common.utilities import read_json_file
    cfg = read_json_file(str(config.connector_config_path()))
    if not cfg:
        log.error("Failed to read connector_config.json from %s", config.connector_config_path())
        return None
    return cfg


def _prime_wal(config: Config) -> None:
    """Open the DB with WAL mode before the accelerator's first write."""
    import sqlite3
    db_file = str(config.db_path)
    con = sqlite3.connect(db_file)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.commit()
    con.close()
