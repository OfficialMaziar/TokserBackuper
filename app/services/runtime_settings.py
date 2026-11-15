"""Runtime settings overrides.

Values saved from the Settings page live in ``system_settings``. They layer on
top of ``app.core.config.settings`` so a change takes effect without a restart,
while the environment/file configuration stays the source of defaults.

Only non-secret, operationally safe keys may be overridden here. Secrets
(SMTP password, tokens) are handled by the services that own them.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.config import settings

# key -> (attribute path on settings, coercion)
OVERRIDABLE: dict[str, tuple[str, type]] = {
    "disk_warning_percent": ("disk_warning_percent", int),
    "disk_critical_percent": ("disk_critical_percent", int),
    "min_free_disk_mb": ("min_free_disk_mb", int),
    "max_concurrent_backups": ("max_concurrent_backups", int),
    "verify_archives": ("verify_archives", bool),
    "timezone": ("timezone", str),
    "default_language": ("default_language", str),
    "default_theme": ("default_theme", str),
}


def _coerce(raw: str, kind: type) -> Any:
    if kind is bool:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if kind is int:
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None
    return str(raw)


def get(db, key: str, default: Any = None) -> Any:
    """Read an effective value: database override, else configured default."""
    from app.models import SystemSetting

    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is None or row.value == "":
        return default
    return row.value


def get_int(db, key: str, default: int) -> int:
    raw = get(db, key)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def get_bool(db, key: str, default: bool) -> bool:
    raw = get(db, key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def apply_overrides(db) -> list[str]:
    """Push stored overrides onto the in-process ``settings`` object.

    Called at startup and after Settings are saved. Returns the keys applied.
    """
    applied: list[str] = []
    for key, (attr, kind) in OVERRIDABLE.items():
        value = get(db, key)
        if value is None:
            continue
        coerced = _coerce(value, kind)
        if coerced is None:
            continue
        setattr(settings, attr, coerced)
        applied.append(key)
    return applied
