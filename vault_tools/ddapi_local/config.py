"""
config.py — Load and validate .env settings.

Reads the root project .env by default (same file used by other vault-tools
scripts). Searches up from the current working directory, so it works both
in development (run from repo root) and when installed via uv tool.

Root .env keys used:
    VAULT_URL       — full URL, e.g. https://myco.veevavault.com
    VAULT_USERNAME  — Vault login email
    VAULT_PASSWORD  — Vault password
    VAULT_VERSION   — API version, e.g. v25.3  (optional, defaults to v24.1)

vault-ddapi-specific keys (add to root .env):
    DB_PATH         — absolute path to the SQLite file
    LOG_PATH        — absolute path to the log file
    WORK_DIR        — absolute path for download scratch space
    EXTRACT_TYPE    — 'incremental' (default) or 'full'
    MAX_RETRIES     — integer, default 3
    RETRY_BACKOFF_SECONDS — float, default 5
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv


class Config:
    def __init__(self, env_file: str | None = None):
        # Search up from CWD (same strategy as log_analyzer), overridable via env var or argument
        env_path = env_file or os.environ.get("DDAPI_ENV_FILE") or find_dotenv(usecwd=True)
        load_dotenv(env_path, override=True)
        self._validate()

    # ------------------------------------------------------------------ #
    # Public properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    def vault_url(self) -> str:
        return os.environ["VAULT_URL"].rstrip("/")

    @property
    def vault_username(self) -> str:
        return os.environ["VAULT_USERNAME"]

    @property
    def vault_password(self) -> str:
        return os.environ["VAULT_PASSWORD"]

    @property
    def vault_api_version(self) -> str:
        # Honour VAULT_VERSION (existing key) or VAULT_API_VERSION if set
        return (
            os.environ.get("VAULT_VERSION")
            or os.environ.get("VAULT_API_VERSION")
            or "v24.1"
        )

    @property
    def db_path(self) -> Path:
        return Path(os.environ["DB_PATH"])

    @property
    def log_path(self) -> Path:
        return Path(os.environ["LOG_PATH"])

    @property
    def work_dir(self) -> Path:
        return Path(os.environ["WORK_DIR"])

    @property
    def extract_type(self) -> str:
        return os.environ.get("EXTRACT_TYPE", "incremental").lower()

    @property
    def max_retries(self) -> int:
        return int(os.environ.get("MAX_RETRIES", "3"))

    @property
    def retry_backoff_seconds(self) -> float:
        return float(os.environ.get("RETRY_BACKOFF_SECONDS", "5"))

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def _validate(self) -> None:
        required = ["VAULT_URL", "VAULT_USERNAME", "VAULT_PASSWORD", "DB_PATH", "LOG_PATH", "WORK_DIR"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise SystemExit(
                f"[vault-ddapi] CRITICAL: Missing required .env variables: {', '.join(missing)}\n"
                f"Add them to the .env file in your project root (or set DDAPI_ENV_FILE to its path)."
            )
