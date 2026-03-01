"""
vault.py — Vault Direct Data API client and pipeline.

Implements the full sync pipeline using the Vault REST API directly:
  1. Authenticate (username/password → session token)
  2. List available Direct Data files
  3. Download the .tar.gz archive (streamed)
  4. Extract archive to WORK_DIR
  5. Load CSV/Parquet data into SQLite

API reference: https://developer.veevavault.com/api/25.3/#Direct_Data
"""

import json
import sqlite3
import tarfile
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import Config
from .logger import get_logger

log = get_logger()

# Sent on every request so it appears in Vault API Usage Logs
_CLIENT_ID = "vault-tools-ddapi"

# extract_type values returned by the API (and accepted as query params)
_TYPE_FULL = "full_directdata"
_TYPE_INCREMENTAL = "incremental_directdata"


# ------------------------------------------------------------------ #
# Retry helper                                                         #
# ------------------------------------------------------------------ #

def _with_retry(fn, config: Config, label: str) -> Any:
    """Call fn(), retrying up to config.max_retries times with exponential backoff."""
    delay = config.retry_backoff_seconds
    for attempt in range(1, config.max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == config.max_retries:
                log.error("%s failed after %d attempts: %s", label, config.max_retries, exc, exc_info=True)
                raise
            log.warning("%s attempt %d/%d failed: %s — retrying in %.0fs",
                        label, attempt, config.max_retries, exc, delay)
            time.sleep(delay)
            delay *= 2


def _headers(session_id: str | None = None) -> dict:
    """Build standard request headers."""
    h = {
        "Accept": "application/json",
        "X-VaultAPI-ClientID": _CLIENT_ID,
    }
    if session_id:
        h["Authorization"] = session_id
    return h


# ------------------------------------------------------------------ #
# Authentication                                                       #
# ------------------------------------------------------------------ #

def _authenticate(config: Config) -> str:
    """POST /api/{version}/auth — returns session ID."""
    url = f"{config.vault_url}/api/{config.vault_api_version}/auth"
    resp = requests.post(
        url,
        data={"username": config.vault_username, "password": config.vault_password},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "X-VaultAPI-ClientID": _CLIENT_ID,
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("responseStatus") != "SUCCESS":
        log.error("Vault auth failed.\nRequest: POST %s\nResponse:\n%s",
                  url, json.dumps(body, indent=2))
        raise RuntimeError(f"Vault auth failed: {body.get('errors', [])}")
    session_id = body["sessionId"]
    log.info("Authenticated to Vault as %s", config.vault_username)
    return session_id


# ------------------------------------------------------------------ #
# List Direct Data files                                               #
# ------------------------------------------------------------------ #

def get_latest_full(config: Config) -> dict | None:
    """Return metadata for the most-recent full extract, or None if unavailable."""
    session_id = _authenticate(config)
    items = _list_direct_data(config, session_id, _TYPE_FULL)
    if not items:
        return None
    items.sort(key=lambda i: i.get("stop_time", ""), reverse=True)
    return items[0]


def get_incrementals_since(config: Config, since: str) -> list[dict]:
    """Return incremental extract metadata since `since`, sorted oldest-first."""
    session_id = _authenticate(config)
    items = _list_direct_data(config, session_id, _TYPE_INCREMENTAL, start_time=since)
    items.sort(key=lambda i: i.get("start_time", ""))
    return items


def _list_direct_data(config: Config, session_id: str, extract_type_filter: str,
                      start_time: str | None = None, stop_time: str | None = None) -> list[dict]:
    """GET /api/{version}/services/directdata/files

    extract_type_filter: full_directdata | incremental_directdata | log_directdata
    start_time / stop_time: ISO 8601, e.g. 2024-01-15T07:00:00Z (optional)
    """
    url = f"{config.vault_url}/api/{config.vault_api_version}/services/directdata/files"
    params: dict = {"extract_type": extract_type_filter}
    if start_time:
        params["start_time"] = start_time
    if stop_time:
        params["stop_time"] = stop_time

    resp = requests.get(url, params=params, headers=_headers(session_id), timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if body.get("responseStatus") != "SUCCESS":
        log.error("Direct Data list failed.\nRequest: GET %s params=%s\nResponse:\n%s",
                  url, params, json.dumps(body, indent=2))
        raise RuntimeError(f"Direct Data list failed: {body.get('errors')}")

    items = body.get("data", [])
    log.info("Retrieved %d %s file(s) from Vault", len(items), extract_type_filter)
    return items


# ------------------------------------------------------------------ #
# Download                                                             #
# ------------------------------------------------------------------ #

def _download_part(session_id: str, url: str, dest: Path) -> None:
    """Stream-download a single file part to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=_headers(session_id), stream=True, timeout=300) as resp:
        if not resp.ok:
            log.error("Download failed.\nRequest: GET %s\nHTTP %s:\n%s",
                      url, resp.status_code, resp.text[:2000])
            resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)
    log.debug("Downloaded %s (%d bytes)", dest.name, dest.stat().st_size)


def _download_items(session_id: str, items: list[dict], download_dir: Path,
                    api_base: str) -> None:
    """Download all file parts for a list of Direct Data items."""
    for item in items:
        parts = item.get("filepart_details") or []
        if parts:
            for part in parts:
                dest = download_dir / part["filename"]
                log.info("Downloading part %d/%d: %s (%s bytes)",
                         part.get("filepart", 1), item.get("fileparts", 1),
                         part["filename"], part.get("size", "?"))
                _download_part(session_id, part["url"], dest)
        else:
            # Fallback: build URL from item name (part name format: {name}.001)
            name = item["name"]
            filename = item.get("filename", f"{name}.tar.gz")
            dest = download_dir / filename
            dl_url = f"{api_base}/services/directdata/files/{name}"
            log.info("Downloading %s (%s bytes)", filename, item.get("size", "?"))
            _download_part(session_id, dl_url, dest)


def apply_item(config: Config, item: dict, extract_type: str) -> bool:
    """Download, extract, load, and clean up a single Direct Data item.

    Returns True on success. The caller is responsible for recording state.
    extract_type should be 'full' or 'incremental' (used for DB upsert logic).
    """
    name = item.get("name", "?")
    stop_time = item.get("stop_time", "?")
    log.info("Applying %s extract: %s (stop_time=%s)", extract_type, name, stop_time)

    download_dir = config.work_dir / "downloads"
    extract_dir = config.work_dir / "extracted"

    # Clean up previous run's files so we don't mix archives
    _clean_dir(download_dir)
    _clean_dir(extract_dir)

    def _run() -> bool:
        session_id = _authenticate(config)
        api_base = f"{config.vault_url}/api/{config.vault_api_version}"
        download_dir.mkdir(parents=True, exist_ok=True)
        _download_items(session_id, [item], download_dir, api_base)
        return True

    try:
        _with_retry(_run, config, f"download {name}")
    except Exception:
        return False

    if not extract_archive(config):
        return False

    if not load_into_db(config, extract_type):
        return False

    return True


def _clean_dir(path: Path) -> None:
    """Remove all files in a directory (not subdirs), creating it if needed."""
    import shutil
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ #
# Extract                                                              #
# ------------------------------------------------------------------ #

def extract_archive(config: Config) -> bool:
    """Extract all Direct Data archives from the downloads dir into extracted/.

    Vault part files are named *.tar.gz.001, *.tar.gz.002, etc.
    Multi-part archives must be concatenated before extraction.
    Single-part files (*.tar.gz.001 only) are extracted directly.
    """
    download_dir = config.work_dir / "downloads"
    extract_dir = config.work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Collect all part files and group by base name (strip the .NNN suffix)
    all_parts = sorted(download_dir.glob("*.tar.gz.*"))
    # Also pick up plain .tar.gz files (no part suffix)
    plain = sorted(list(download_dir.glob("*.tar.gz")) + list(download_dir.glob("*.tgz")))

    if not all_parts and not plain:
        log.error("No archive files found in %s", download_dir)
        return False

    # Group parts by base archive name
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for p in all_parts:
        # e.g. foo.tar.gz.001 → base = foo.tar.gz
        base = p.name.rsplit(".", 1)[0]  # strip the .001 / .002 suffix
        groups[base].append(p)
    for p in plain:
        if p.name not in groups:
            groups[p.name].append(p)

    for base_name, parts in sorted(groups.items()):
        parts = sorted(parts)
        log.info("Extracting %s (%d part(s)) → %s", base_name, len(parts), extract_dir)
        try:
            if len(parts) == 1:
                # Single part — open directly regardless of .001 suffix
                with tarfile.open(fileobj=open(parts[0], "rb"), mode="r:gz") as tar:
                    tar.extractall(path=extract_dir)
            else:
                # Multi-part — concatenate into a stream and extract
                import io

                class _CatStream(io.RawIOBase):
                    """Concatenate multiple files as a single stream."""
                    def __init__(self, paths):
                        self._paths = list(paths)
                        self._fh = open(self._paths.pop(0), "rb")

                    def readinto(self, b):
                        while True:
                            n = self._fh.readinto(b)
                            if n:
                                return n
                            self._fh.close()
                            if not self._paths:
                                return 0
                            self._fh = open(self._paths.pop(0), "rb")

                stream = io.BufferedReader(_CatStream(parts))
                with tarfile.open(fileobj=stream, mode="r:gz") as tar:
                    tar.extractall(path=extract_dir)

        except Exception as exc:
            log.error("Failed to extract %s: %s", base_name, exc, exc_info=True)
            return False

    return True


# ------------------------------------------------------------------ #
# Load into SQLite                                                     #
# ------------------------------------------------------------------ #

def load_into_db(config: Config, extract_type: str) -> bool:
    """Load extracted data into SQLite using the manifest.

    Manifest columns (actual Vault format):
      extract       — dot-separated name e.g. Object.activity__v  → table name
      extract_label — human label (ignored)
      type          — 'updates' or 'deletes'
      records       — row count (skip if 0 or file is empty)
      file          — relative path to CSV within extracted dir (empty when records=0)
    """
    extract_dir = config.work_dir / "extracted"

    _prime_wal(config)

    con = sqlite3.connect(str(config.db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    try:
        manifest_path = extract_dir / "manifest.csv"
        if not manifest_path.exists():
            log.error("manifest.csv not found in %s", extract_dir)
            return False

        manifest_df = pd.read_csv(manifest_path)
        total = len(manifest_df)
        loaded = 0

        for _, row in manifest_df.iterrows():
            rel_file = str(row.get("file", "") or "").strip()
            records = int(row.get("records", 0) or 0)

            # Skip empty extracts
            if not rel_file or records == 0:
                continue

            file_path = extract_dir / rel_file
            if not file_path.exists():
                log.warning("Manifest file missing on disk: %s", rel_file)
                continue

            # Table name: replace dots and hyphens with underscores
            extract_name = str(row.get("extract", file_path.stem))
            table = extract_name.replace(".", "_").replace("-", "_")

            row_type = str(row.get("type", "updates")).strip().lower()
            log.info("Loading %s → %s (%s, %d records)", rel_file, table, row_type, records)

            if row_type == "deletes":
                _apply_deletes(con, table, file_path)
            else:
                _load_csv_to_table(con, table, file_path, create_if_missing=True)

            loaded += 1

        con.commit()
        log.info("DB load complete: %d/%d manifest entries applied → %s", loaded, total, config.db_path)
        return True

    except Exception as exc:
        log.error("DB load failed: %s", exc, exc_info=True)
        con.rollback()
        return False
    finally:
        con.close()


def _apply_deletes(con: sqlite3.Connection, table: str, path: Path) -> None:
    """Delete rows from table whose id appears in the deletes CSV."""
    # Ensure table exists before trying to delete (may not exist on first run edge cases)
    existing_tables = {
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if table not in existing_tables:
        log.debug("Skip deletes for %s — table does not exist yet", table)
        return

    for chunk in pd.read_csv(path, chunksize=50_000, low_memory=False, usecols=["id"]):
        ids = chunk["id"].dropna().tolist()
        if ids:
            placeholders = ",".join("?" for _ in ids)
            con.execute(f'DELETE FROM "{table}" WHERE id IN ({placeholders})', ids)
            log.debug("Deleted %d row(s) from %s", len(ids), table)


def _load_csv_to_table(con: sqlite3.Connection, table: str, path: Path,
                       create_if_missing: bool = True) -> None:
    """Append CSV rows into a SQLite table, upserting by id (delete-then-insert)."""
    first = True
    for chunk in pd.read_csv(path, chunksize=50_000, low_memory=False):
        if chunk.empty:
            continue
        chunk = chunk.copy()
        chunk.columns = [c.replace(" ", "_").replace("-", "_") for c in chunk.columns]

        if first and create_if_missing:
            cols_ddl = ", ".join(f'"{c}" TEXT' for c in chunk.columns)
            con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_ddl})')
            existing = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
            for col in chunk.columns:
                if col not in existing:
                    con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')
            first = False

        # Delete-then-insert so updates overwrite existing rows
        if "id" in chunk.columns:
            ids = chunk["id"].dropna().tolist()
            if ids:
                placeholders = ",".join("?" for _ in ids)
                con.execute(f'DELETE FROM "{table}" WHERE id IN ({placeholders})', ids)

        # SQLite limit is 999 bind variables; compute safe row batch size
        sql_chunksize = max(1, 999 // len(chunk.columns))
        chunk.to_sql(table, con, if_exists="append", index=False, method="multi", chunksize=sql_chunksize)


def _prime_wal(config: Config) -> None:
    """Ensure DB and parent dirs exist with WAL mode before first write."""
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(config.db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.commit()
    con.close()
