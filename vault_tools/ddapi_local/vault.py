"""
vault.py — Vault Direct Data API client and pipeline.

Implements the full sync pipeline using the Vault REST API directly:
  1. Authenticate (username/password → session token)
  2. List available Direct Data files
  3. Download the .tar.gz archive (streamed)
  4. Extract archive to WORK_DIR
  5. Load CSV/Parquet data into SQLite

The accelerator package (vault-direct-data-api-accelerators) ships only
common/utilities.py in its wheel — the scripts and services are not importable
when installed via uv/pip. We implement the pipeline here using requests directly.
"""

import io
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
            log.warning("%s attempt %d/%d failed: %s — retrying in %.0fs", label, attempt, config.max_retries, exc, delay)
            time.sleep(delay)
            delay *= 2


# ------------------------------------------------------------------ #
# Authentication                                                       #
# ------------------------------------------------------------------ #

def _authenticate(config: Config) -> str:
    """POST /api/{version}/auth — returns session ID."""
    url = f"{config.vault_url}/api/{config.vault_api_version}/auth"
    resp = requests.post(
        url,
        data={"username": config.vault_username, "password": config.vault_password},
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("responseStatus") != "SUCCESS":
        log.error(
            "Vault auth failed.\nRequest: POST %s\nResponse:\n%s",
            url, json.dumps(body, indent=2),
        )
        raise RuntimeError(f"Vault auth failed: {body.get('errors', [])}")
    session_id = body["sessionId"]
    log.info("Authenticated to Vault as %s", config.vault_username)
    return session_id


# ------------------------------------------------------------------ #
# List Direct Data files                                               #
# ------------------------------------------------------------------ #

def _list_direct_data(config: Config, session_id: str, extract_type: str,
                      start_time: str | None, stop_time: str | None) -> list[dict]:
    """GET /services/directdata/files — returns list of available file items."""
    url = f"{config.vault_url}/api/{config.vault_api_version}/services/directdata/files"
    params: dict = {"extract_type": extract_type.upper()}
    if start_time:
        params["start_time"] = start_time
    if stop_time:
        params["stop_time"] = stop_time

    resp = requests.get(
        url,
        params=params,
        headers={"Authorization": session_id, "Accept": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("responseStatus") != "SUCCESS":
        log.error(
            "Direct Data list failed.\nRequest: GET %s params=%s\nResponse:\n%s",
            url, params, json.dumps(body, indent=2),
        )
        raise RuntimeError(f"Direct Data list failed: {body.get('errors')}")

    items = body.get("data", [])
    log.info("Found %d Direct Data file(s) for extract_type=%s", len(items), extract_type.upper())
    return items


# ------------------------------------------------------------------ #
# Download                                                             #
# ------------------------------------------------------------------ #

def _download_file_part(session_id: str, url: str, dest: Path) -> None:
    """Stream-download a single file part to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers={"Authorization": session_id}, stream=True, timeout=300) as resp:
        if not resp.ok:
            log.error(
                "Download failed.\nRequest: GET %s\nHTTP %s: %s",
                url, resp.status_code, resp.text[:2000],
            )
            resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)
    log.debug("Downloaded %s (%d bytes)", dest.name, dest.stat().st_size)


def download_direct_data(config: Config, extract_type: str,
                         start_time: str | None, stop_time: str | None) -> bool:
    """Authenticate, list, and download all Direct Data parts. Returns True on success."""

    def _run() -> bool:
        session_id = _authenticate(config)
        items = _list_direct_data(config, session_id, extract_type, start_time, stop_time)

        if not items:
            log.warning("No Direct Data files available for extract_type=%s (range: %s → %s)",
                        extract_type, start_time, stop_time)
            return False

        download_dir = config.work_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        for item in items:
            parts = item.get("filepart_details") or []
            if not parts:
                # Single-part — download via the item name
                name = item["name"]
                filename = item.get("filename", name)
                dest = download_dir / filename
                dl_url = f"{config.vault_url}/api/{config.vault_api_version}/services/directdata/files/{name}"
                log.info("Downloading %s (%s bytes)", filename, item.get("size", "?"))
                _download_file_part(session_id, dl_url, dest)
            else:
                for part in parts:
                    dest = download_dir / part["filename"]
                    log.info("Downloading part %d: %s (%s bytes)",
                             part.get("filepart", 1), part["filename"], part.get("size", "?"))
                    _download_file_part(session_id, part["url"], dest)

        return True

    try:
        return _with_retry(_run, config, f"download_direct_data ({extract_type})")
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Extract                                                              #
# ------------------------------------------------------------------ #

def extract_archive(config: Config) -> bool:
    """Extract all .tar.gz files from the downloads dir into extracted/."""
    download_dir = config.work_dir / "downloads"
    extract_dir = config.work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    archives = list(download_dir.glob("*.tar.gz")) + list(download_dir.glob("*.tgz"))
    if not archives:
        log.error("No .tar.gz archives found in %s", download_dir)
        return False

    for archive in archives:
        log.info("Extracting %s → %s", archive.name, extract_dir)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(path=extract_dir)
        except Exception as exc:
            log.error("Failed to extract %s: %s", archive.name, exc, exc_info=True)
            return False

    return True


# ------------------------------------------------------------------ #
# Load into SQLite                                                     #
# ------------------------------------------------------------------ #

def load_into_db(config: Config, extract_type: str) -> bool:
    """Load extracted CSV/Parquet data into SQLite. Returns True on success."""
    extract_dir = config.work_dir / "extracted"

    # Ensure DB exists with WAL mode
    _prime_wal(config)

    con = sqlite3.connect(str(config.db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    try:
        # Read metadata for column types if available
        metadata_df = _read_metadata(extract_dir)

        # Read manifest to get ordered list of files to load
        manifest_df = _read_manifest(extract_dir)

        if manifest_df is not None:
            for _, row in manifest_df.iterrows():
                _process_manifest_row(row, extract_dir, extract_type, con, metadata_df, config)
        else:
            # No manifest — load all CSV/Parquet files we find
            for data_file in sorted(extract_dir.rglob("*.csv")):
                if "metadata" in data_file.name.lower() or "manifest" in data_file.name.lower():
                    continue
                table = data_file.stem.replace("-", "_")
                log.info("Loading %s → table %s", data_file.name, table)
                _load_csv_to_table(con, table, data_file, extract_type)

        con.commit()
        log.info("DB load complete: %s", config.db_path)
        return True

    except Exception as exc:
        log.error("DB load failed: %s", exc, exc_info=True)
        con.rollback()
        return False
    finally:
        con.close()


def _read_metadata(extract_dir: Path) -> pd.DataFrame | None:
    for candidate in ["metadata_full.csv", "metadata.csv"]:
        p = _find_file(extract_dir, candidate)
        if p:
            try:
                return pd.read_csv(p)
            except Exception:
                pass
    return None


def _read_manifest(extract_dir: Path) -> pd.DataFrame | None:
    p = _find_file(extract_dir, "manifest.csv")
    if p:
        try:
            return pd.read_csv(p)
        except Exception:
            pass
    return None


def _find_file(base: Path, name: str) -> Path | None:
    matches = list(base.rglob(name))
    return matches[0] if matches else None


def _process_manifest_row(row: Any, extract_dir: Path, extract_type: str,
                          con: sqlite3.Connection, metadata_df: pd.DataFrame | None,
                          config: Config) -> None:
    """Load a single entry from the manifest."""
    # Manifest columns vary; try common names
    filename = row.get("filename") or row.get("file_name") or row.get("name", "")
    if not filename:
        return

    file_path = _find_file(extract_dir, Path(filename).name)
    if file_path is None:
        log.warning("Manifest file not found in extracted dir: %s", filename)
        return

    # Derive table name from filename stem (strip extract-type prefix/suffix)
    table = file_path.stem.replace("-", "_")
    # Strip common suffixes like _full, _incremental
    for suffix in ("_full", "_incremental", "_log"):
        if table.lower().endswith(suffix):
            table = table[: -len(suffix)]
            break

    row_extract_type = str(row.get("extract_type", extract_type)).lower()
    log.info("Loading %s → table %s (type=%s)", file_path.name, table, row_extract_type)

    if file_path.suffix == ".parquet":
        _load_parquet_to_table(con, table, file_path, row_extract_type)
    else:
        _load_csv_to_table(con, table, file_path, row_extract_type)


def _load_csv_to_table(con: sqlite3.Connection, table: str, path: Path, extract_type: str) -> None:
    """Load a CSV into a SQLite table, chunked."""
    first = True
    for chunk in pd.read_csv(path, chunksize=50_000, low_memory=False):
        _upsert_chunk(con, table, chunk, extract_type, create=first)
        first = False


def _load_parquet_to_table(con: sqlite3.Connection, table: str, path: Path, extract_type: str) -> None:
    """Load a Parquet file into a SQLite table, chunked."""
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    first = True
    for batch in pf.iter_batches(batch_size=50_000):
        chunk = batch.to_pandas()
        _upsert_chunk(con, table, chunk, extract_type, create=first)
        first = False


def _upsert_chunk(con: sqlite3.Connection, table: str, df: pd.DataFrame,
                  extract_type: str, create: bool) -> None:
    """Write a DataFrame chunk into SQLite.

    Full / log extracts: append rows.
    Incremental extracts: delete-then-insert on id column (if present).
    """
    if df.empty:
        return

    # Sanitise column names
    df = df.copy()
    df.columns = [c.replace(" ", "_").replace("-", "_") for c in df.columns]

    if create:
        # CREATE TABLE IF NOT EXISTS with TEXT columns; ALTER for new ones later
        cols_ddl = ", ".join(f'"{c}" TEXT' for c in df.columns)
        con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_ddl})')
        # Add any missing columns (schema evolution)
        existing = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        for col in df.columns:
            if col not in existing:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')

    if extract_type == "incremental" and "id" in df.columns:
        ids = df["id"].dropna().tolist()
        if ids:
            placeholders = ",".join("?" for _ in ids)
            con.execute(f'DELETE FROM "{table}" WHERE id IN ({placeholders})', ids)

    df.to_sql(table, con, if_exists="append", index=False, method="multi", chunksize=1000)


def _prime_wal(config: Config) -> None:
    """Ensure DB file and parent dirs exist with WAL mode before any writes."""
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(config.db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.commit()
    con.close()
