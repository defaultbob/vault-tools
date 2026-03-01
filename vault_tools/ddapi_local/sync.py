"""
sync.py — Orchestration: decide full vs incremental, run the pipeline.
"""

from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .db import (
    get_last_sync,
    record_full_sync,
    record_incremental_sync,
)
from .logger import get_logger
from .vault import download_direct_data, extract_archive, load_into_db

log = get_logger()


def run(config: Config, force_full: bool = False) -> None:
    """Main sync entry point."""
    db_exists = config.db_path.exists()
    force_full = force_full or config.extract_type == "full"

    if not db_exists or force_full:
        _full_seed(config)
    else:
        _incremental_sync(config)


# ------------------------------------------------------------------ #
# Full seed                                                            #
# ------------------------------------------------------------------ #

def _full_seed(config: Config) -> None:
    log.info("Starting FULL seed → %s", config.db_path)

    ok = download_direct_data(config, extract_type="full", start_time=None, stop_time=None)
    if not ok:
        log.error("Full seed aborted: download failed")
        return

    ok = extract_archive(config)
    if not ok:
        log.error("Full seed aborted: extraction failed")
        return

    ok = load_into_db(config, extract_type="full")
    if not ok:
        log.error("Full seed aborted: DB load failed")
        return

    record_full_sync(config.db_path)
    log.info("Full seed complete.")


# ------------------------------------------------------------------ #
# Incremental sync                                                     #
# ------------------------------------------------------------------ #

def _incremental_sync(config: Config) -> None:
    meta = get_last_sync(config.db_path)
    last_sync = meta.get("last_inc") or meta.get("last_full")

    if not last_sync:
        log.warning("No last sync timestamp found — falling back to full seed")
        _full_seed(config)
        return

    stop_time = datetime.now(timezone.utc).isoformat()
    log.info("Starting INCREMENTAL sync: %s → %s", last_sync, stop_time)

    ok = download_direct_data(
        config,
        extract_type="incremental",
        start_time=last_sync,
        stop_time=stop_time,
    )
    if not ok:
        log.error("Incremental sync aborted: download failed (will retry next run)")
        return

    ok = extract_archive(config)
    if not ok:
        log.error("Incremental sync aborted: extraction failed")
        return

    ok = load_into_db(config, extract_type="incremental")
    if not ok:
        log.error("Incremental sync aborted: DB load failed")
        return

    record_incremental_sync(config.db_path)
    log.info("Incremental sync complete.")
