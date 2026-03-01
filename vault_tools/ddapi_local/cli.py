"""
cli.py — Entry point for the `ddapi-local` command.

Usage:
    ddapi-local sync [--full]
    ddapi-local status
"""

import argparse
import sys

from .config import Config
from .db import get_last_sync, table_counts
from .logger import setup_logger
from .sync import run as sync_run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ddapi-local",
        description="Sync Veeva Vault data to a local SQLite database.",
    )
    sub = parser.add_subparsers(dest="command")

    # sync
    sync_parser = sub.add_parser("sync", help="Run a sync (auto-detects full vs incremental)")
    sync_parser.add_argument(
        "--full",
        action="store_true",
        help="Force a full seed even if the database already exists",
    )

    # status
    sub.add_parser("status", help="Show last sync timestamps and row counts")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Config raises SystemExit(1) on missing required fields
    config = Config()
    setup_logger(config.log_path)

    if args.command == "sync":
        sync_run(config, force_full=args.full)

    elif args.command == "status":
        _print_status(config)


def _print_status(config: Config) -> None:
    meta = get_last_sync(config.db_path)
    print(f"Database : {config.db_path}")
    print(f"Last full seed  : {meta['last_full'] or 'never'}")
    print(f"Last incremental: {meta['last_inc'] or 'never'}")
    print()
    counts = table_counts(config.db_path)
    if counts:
        max_len = max(len(t) for t in counts)
        print(f"{'Table':<{max_len}}   Rows")
        print("-" * (max_len + 12))
        for table, count in sorted(counts.items()):
            print(f"{table:<{max_len}}   {count:,}")
    else:
        print("(database is empty or does not exist)")
