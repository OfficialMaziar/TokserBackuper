"""Central logging configuration with rotating file handlers."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.core.config import settings

_CONFIGURED = False

FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class RedactFilter(logging.Filter):
    """Strip obvious secrets from log records before they hit disk."""

    _KEYS = ("password", "token", "secret", "authorization", "api_key", "bot_token")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:
            return True
        lowered = msg.lower()
        for key in self._KEYS:
            if key in lowered:
                # Do not try to rewrite arbitrary text; just flag it.
                record.msg = msg + " [redacted-context]"
                record.args = ()
                break
        return True


def setup_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    lvl = getattr(logging, (level or ("DEBUG" if settings.debug else "INFO")).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(lvl)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = logging.Formatter(FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "tokser.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(RedactFilter())
    root.addHandler(file_handler)

    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(fmt)
    root.addHandler(err_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(lvl)
    root.addHandler(console)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
