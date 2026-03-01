"""
config.py — Load and validate .env settings.

Reads the root project .env by default (same file used by other vault-tools
scripts). The accelerator JSON config files are generated at runtime in WORK_DIR.

Root .env keys used:
    VAULT_URL       — full URL, e.g. https://myco.veevavault.com
    VAULT_USERNAME  — Vault login email
    VAULT_PASSWORD  — Vault password
    VAULT_VERSION   — API version, e.g. v25.3  (optional, defaults to v24.1)

ddapi-local-specific keys (add to root .env):
    DB_PATH         — absolute path to the SQLite file
    LOG_PATH        — absolute path to the log file
    WORK_DIR        — absolute path for download scratch space
    EXTRACT_TYPE    — 'incremental' (default) or 'full'
    MAX_RETRIES     — integer, default 3
    RETRY_BACKOFF_SECONDS — float, default 5
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Root of the vault-tools project (three levels up from vault_tools/ddapi_local/config.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Config:
    def __init__(self, env_file: str | None = None):
        # Default: root .env, overridable via DDAPI_ENV_FILE env var or argument
        env_path = env_file or os.environ.get("DDAPI_ENV_FILE", str(_PROJECT_ROOT / ".env"))
        load_dotenv(env_path, override=True)
        self._validate()

    # ------------------------------------------------------------------ #
    # Public properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    def vault_url(self) -> str:
        return os.environ["VAULT_URL"].rstrip("/")

    @property
    def vault_dns(self) -> str:
        """Hostname only — required by the accelerator's vapil_settings.json."""
        return urlparse(self.vault_url).hostname or self.vault_url

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
    def db_folder(self) -> str:
        return str(self.db_path.parent)

    @property
    def db_name(self) -> str:
        return self.db_path.name

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
    # Accelerator config file generators                                   #
    # ------------------------------------------------------------------ #

    def vapil_settings_path(self) -> Path:
        return self.work_dir / "vapil_settings.json"

    def connector_config_path(self) -> Path:
        return self.work_dir / "connector_config.json"

    def write_accelerator_configs(
        self,
        extract_type: str,
        start_time: str | None = None,
        stop_time: str | None = None,
    ) -> None:
        """Write the JSON config files the accelerator expects."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        vapil = {
            "vault_dns": self.vault_dns,
            "vault_client_id": "ddapi-local",
            "authentication_type": "BASIC",
            "vault_username": self.vault_username,
            "vault_password": self.vault_password,
            "api_version": self.vault_api_version,
        }
        (self.work_dir / "vapil_settings.json").write_text(json.dumps(vapil, indent=2))

        direct_data: dict = {"extract_type": extract_type}
        if start_time:
            direct_data["start_time"] = start_time
        if stop_time:
            direct_data["stop_time"] = stop_time

        connector = {
            "direct_data": direct_data,
            "local": {
                "local_folder": str(self.work_dir),
                "extract_folder": str(self.work_dir / "extracted"),
            },
            "sqlite": {
                "databases_folder": self.db_folder,
                "database": self.db_name,
            },
        }
        (self.work_dir / "connector_config.json").write_text(json.dumps(connector, indent=2))

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def _validate(self) -> None:
        required = ["VAULT_URL", "VAULT_USERNAME", "VAULT_PASSWORD", "DB_PATH", "LOG_PATH", "WORK_DIR"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise SystemExit(
                f"[ddapi-local] CRITICAL: Missing required .env variables: {', '.join(missing)}\n"
                f"Add them to {_PROJECT_ROOT / '.env'}"
            )
