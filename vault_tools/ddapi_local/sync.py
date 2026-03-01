"""
sync.py — Orchestration: decide full vs incremental, run the pipeline.

Sync strategy:
  First run (no DB or --full):
    1. Download and apply the most recent full extract
    2. Apply all incremental extracts since the full's stop_time, in order
    3. Record the stop_time of the last incremental applied

  Subsequent runs:
    1. Query for all incremental extracts since last recorded stop_time
    2. Apply each in chronological order
    3. Record stop_time after each one (so a mid-run failure resumes correctly)
"""

from .config import Config
from .db import get_last_sync, record_full_sync, record_incremental_sync
from .logger import get_logger
from .vault import apply_item, get_incrementals_since, get_latest_full

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

    full_item = get_latest_full(config)
    if not full_item:
        log.error("Full seed aborted: no full extract available from Vault")
        return

    log.info("Full extract: %s (stop_time=%s)", full_item["name"], full_item.get("stop_time"))

    if not apply_item(config, full_item, extract_type="full"):
        log.error("Full seed aborted: failed to apply full extract")
        return

    full_stop = full_item.get("stop_time", "")
    record_full_sync(config.db_path, full_stop)
    log.info("Full seed applied. Catching up incrementals since %s …", full_stop)

    # Apply all incrementals that have been generated since the full's stop_time
    _apply_incrementals(config, since=full_stop, context="catch-up")

    log.info("Full seed complete.")


# ------------------------------------------------------------------ #
# Incremental sync                                                     #
# ------------------------------------------------------------------ #

def _incremental_sync(config: Config) -> None:
    meta = get_last_sync(config.db_path)
    since = meta.get("last_inc") or meta.get("last_full")

    if not since:
        log.warning("No last sync position found — falling back to full seed")
        _full_seed(config)
        return

    log.info("Starting INCREMENTAL sync since %s", since)
    _apply_incrementals(config, since=since, context="incremental")


# ------------------------------------------------------------------ #
# Shared: apply a sequence of incrementals                             #
# ------------------------------------------------------------------ #

def _apply_incrementals(config: Config, since: str, context: str) -> None:
    """Fetch and apply all incremental extracts since `since`, oldest-first.

    Records stop_time in the DB after each successful apply so a failure
    mid-sequence resumes from the last completed item, not the beginning.
    """
    items = get_incrementals_since(config, since=since)

    if not items:
        log.info("No new incremental extracts available since %s", since)
        return

    log.info("Applying %d incremental extract(s) [%s]", len(items), context)

    for i, item in enumerate(items, 1):
        name = item.get("name", "?")
        item_stop = item.get("stop_time", "")
        log.info("[%d/%d] Applying incremental: %s (stop_time=%s)", i, len(items), name, item_stop)

        if not apply_item(config, item, extract_type="incremental"):
            log.error(
                "Incremental sync stopped at %s — will resume from %s on next run",
                name, item.get("start_time", since),
            )
            return

        # Record after each success so failures mid-sequence don't re-apply
        if item_stop:
            record_incremental_sync(config.db_path, item_stop)

    log.info("All incremental extracts applied [%s]", context)
