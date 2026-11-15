"""Application configuration.

Configuration is layered:
  1. Built-in defaults
  2. config.yaml (optional, next to the project root)
  3. Environment variables / .env  (highest priority)

Secrets are never hard-coded. On first boot a random SECRET_KEY and
ENCRYPTION_KEY are generated and persisted to the data directory with
restrictive permissions.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("TBM_DATA_DIR", BASE_DIR / "data"))
BACKUP_DIR = Path(os.environ.get("TBM_BACKUP_DIR", BASE_DIR / "backups"))
LOG_DIR = Path(os.environ.get("TBM_LOG_DIR", BASE_DIR / "logs"))
TMP_DIR = DATA_DIR / "tmp"

APP_NAME = "Tokser Backup Manager"
APP_SHORT = "TBM"
APP_VERSION = "1.0.0"
VENDOR = "TokserTeam"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _persist_generated_secret(path: Path) -> str:
    """Create a random secret once and store it with 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


@dataclass
class Settings:
    app_name: str = APP_NAME
    version: str = APP_VERSION
    env: str = "production"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8000
    root_path: str = ""

    # Database ------------------------------------------------------------
    database_url: str = ""

    # Security ------------------------------------------------------------
    secret_key: str = ""
    encryption_key: str = ""
    session_cookie: str = "tbm_session"
    session_ttl_hours: int = 12
    session_secure_cookie: bool = False
    csrf_header: str = "X-CSRF-Token"
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    rate_limit_per_minute: int = 120
    allowed_hosts: list[str] = field(default_factory=list)
    trust_proxy_headers: bool = False

    # Backup engine -------------------------------------------------------
    backup_dir: str = ""
    max_concurrent_backups: int = 2
    verify_archives: bool = True
    default_compression: str = "tar.gz"
    default_compression_level: int = 6
    archive_name_template: str = "{job}_{timestamp}"
    min_free_disk_mb: int = 512

    # Telegram ------------------------------------------------------------
    telegram_api_base: str = "https://api.telegram.org"
    telegram_max_upload_bytes: int = 49 * 1024 * 1024
    telegram_upload_retries: int = 3
    telegram_timeout_seconds: int = 300

    # Monitoring ----------------------------------------------------------
    disk_warning_percent: int = 85
    disk_critical_percent: int = 95
    monitoring_interval_seconds: int = 60

    # Scheduler -----------------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 15
    timezone: str = "UTC"

    # UI ------------------------------------------------------------------
    default_language: str = "en"
    default_theme: str = "dark"

    data_dir: str = ""
    log_dir: str = ""
    tmp_dir: str = ""

    def __post_init__(self) -> None:
        load_dotenv(BASE_DIR / ".env")
        yaml_cfg = _read_yaml(BASE_DIR / "config.yaml")
        env = os.environ

        def pick(env_key: str, yaml_key: str, default: Any) -> Any:
            # An empty value means "not set" in both sources. config.example.yaml
            # ships with blank strings for auto-derived fields (database_url,
            # backup_dir), and treating those as real values produced an empty
            # SQLAlchemy URL that failed at import time.
            if env_key in env and env[env_key] != "":
                return env[env_key]
            value = yaml_cfg.get(yaml_key)
            if value is not None and value != "":
                return value
            return default

        self.env = str(pick("TBM_ENV", "env", self.env))
        self.debug = _bool(pick("TBM_DEBUG", "debug", self.debug))
        self.host = str(pick("TBM_HOST", "host", self.host))
        self.port = _int(pick("TBM_PORT", "port", self.port), self.port)
        self.root_path = str(pick("TBM_ROOT_PATH", "root_path", self.root_path))

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        self.data_dir = str(DATA_DIR)
        self.log_dir = str(LOG_DIR)
        self.tmp_dir = str(TMP_DIR)
        self.backup_dir = str(pick("TBM_BACKUP_DIR", "backup_dir", BACKUP_DIR))

        self.database_url = str(
            pick(
                "TBM_DATABASE_URL",
                "database_url",
                f"sqlite:///{(DATA_DIR / 'tokser.db').as_posix()}",
            )
        )

        secret = pick("TBM_SECRET_KEY", "secret_key", "")
        self.secret_key = str(secret) if secret else _persist_generated_secret(DATA_DIR / ".secret_key")
        enc = pick("TBM_ENCRYPTION_KEY", "encryption_key", "")
        self.encryption_key = str(enc) if enc else _persist_generated_secret(DATA_DIR / ".encryption_key")

        self.session_ttl_hours = _int(pick("TBM_SESSION_TTL", "session_ttl_hours", self.session_ttl_hours), 12)
        self.session_secure_cookie = _bool(
            pick("TBM_SECURE_COOKIE", "session_secure_cookie", self.session_secure_cookie)
        )
        self.login_max_attempts = _int(pick("TBM_LOGIN_MAX_ATTEMPTS", "login_max_attempts", 5), 5)
        self.login_lockout_minutes = _int(pick("TBM_LOGIN_LOCKOUT", "login_lockout_minutes", 15), 15)
        self.rate_limit_per_minute = _int(pick("TBM_RATE_LIMIT", "rate_limit_per_minute", 120), 120)
        self.trust_proxy_headers = _bool(pick("TBM_TRUST_PROXY", "trust_proxy_headers", False))
        hosts = pick("TBM_ALLOWED_HOSTS", "allowed_hosts", "")
        if isinstance(hosts, str) and hosts:
            self.allowed_hosts = [h.strip() for h in hosts.split(",") if h.strip()]
        elif isinstance(hosts, list):
            self.allowed_hosts = [str(h) for h in hosts]

        self.max_concurrent_backups = _int(
            pick("TBM_MAX_CONCURRENT", "max_concurrent_backups", 2), 2
        )
        self.verify_archives = _bool(pick("TBM_VERIFY", "verify_archives", True))
        self.default_compression = str(pick("TBM_COMPRESSION", "default_compression", "tar.gz"))
        self.default_compression_level = _int(
            pick("TBM_COMPRESSION_LEVEL", "default_compression_level", 6), 6
        )
        self.min_free_disk_mb = _int(pick("TBM_MIN_FREE_MB", "min_free_disk_mb", 512), 512)

        self.telegram_api_base = str(
            pick("TBM_TELEGRAM_API", "telegram_api_base", self.telegram_api_base)
        ).rstrip("/")
        self.telegram_max_upload_bytes = _int(
            pick("TBM_TELEGRAM_MAX_UPLOAD", "telegram_max_upload_bytes", self.telegram_max_upload_bytes),
            self.telegram_max_upload_bytes,
        )
        self.telegram_upload_retries = _int(
            pick("TBM_TELEGRAM_RETRIES", "telegram_upload_retries", 3), 3
        )

        self.disk_warning_percent = _int(
            pick("TBM_DISK_WARN", "disk_warning_percent", 85), 85
        )
        self.disk_critical_percent = _int(
            pick("TBM_DISK_CRIT", "disk_critical_percent", 95), 95
        )
        self.scheduler_enabled = _bool(pick("TBM_SCHEDULER", "scheduler_enabled", True))
        self.scheduler_tick_seconds = _int(
            pick("TBM_SCHEDULER_TICK", "scheduler_tick_seconds", 15), 15
        )
        self.timezone = str(pick("TBM_TIMEZONE", "timezone", "UTC"))
        self.default_language = str(pick("TBM_LANGUAGE", "default_language", "en"))
        self.default_theme = str(pick("TBM_THEME", "default_theme", "dark"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
