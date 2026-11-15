"""System settings, notification preferences, activity logs and health."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, require_admin, require_permission
from app.core.config import APP_NAME, APP_VERSION, VENDOR, settings as app_settings
from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models import ActivityLog, Notification, NotificationSetting, SystemSetting, User
from app.schemas import (
    ActivityOut,
    NotificationOut,
    NotificationSettingIn,
    NotificationSettingOut,
    SettingsUpdate,
)
from app.services import auth as auth_svc
from app.services.notifications import EVENT_LABELS, ensure_default_settings
from app.services.scheduler import status as scheduler_status
from app.utils import disk_usage, utcnow

router = APIRouter(prefix="/api/v1", tags=["settings"])

# Keys editable from the UI (stored in system_settings, override defaults).
EDITABLE_KEYS = {
    "app_title", "default_language", "default_theme", "accent_color",
    "timezone", "disk_warning_percent", "disk_critical_percent",
    "min_free_disk_mb", "verify_archives", "max_concurrent_backups",
    "smtp_host", "smtp_port", "smtp_username", "smtp_from", "smtp_to", "smtp_tls",
}
SECRET_KEYS = {"smtp_password"}
BOOL_KEYS = {"verify_archives", "smtp_tls"}
INT_KEYS = {"disk_warning_percent", "disk_critical_percent", "min_free_disk_mb", "max_concurrent_backups", "smtp_port"}


def _get_all(db: Session) -> dict[str, str]:
    rows = db.scalars(select(SystemSetting)).all()
    return {r.key: r.value for r in rows}


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stored = _get_all(db)
    public = {}
    for key in EDITABLE_KEYS:
        public[key] = stored.get(key, "")
    for key in SECRET_KEYS:
        value = decrypt_secret(stored.get(key, "")) if stored.get(key) else ""
        public[key] = mask_secret(value) if value else ""
    return {
        "values": public,
        "defaults": {
            "app_title": APP_NAME,
            "default_language": app_settings.default_language,
            "default_theme": app_settings.default_theme,
            "accent_color": "#6366f1",
            "timezone": app_settings.timezone,
            "disk_warning_percent": app_settings.disk_warning_percent,
            "disk_critical_percent": app_settings.disk_critical_percent,
            "min_free_disk_mb": app_settings.min_free_disk_mb,
            "verify_archives": app_settings.verify_archives,
            "max_concurrent_backups": app_settings.max_concurrent_backups,
        },
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "vendor": VENDOR,
            "environment": app_settings.env,
            "backup_dir": app_settings.backup_dir,
            "database": "sqlite" if app_settings.is_sqlite else "postgresql",
        },
    }


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    updated = []
    for key, raw in (payload.values or {}).items():
        if key not in EDITABLE_KEYS and key not in SECRET_KEYS:
            continue
        if key in SECRET_KEYS:
            if not raw:
                continue
            value = encrypt_secret(str(raw))
            is_secret = True
        else:
            if key in BOOL_KEYS:
                value = "true" if str(raw).lower() in {"1", "true", "yes", "on"} else "false"
            elif key in INT_KEYS:
                try:
                    value = str(int(raw))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"Invalid integer for {key}")
            else:
                value = str(raw)[:1024]
            is_secret = False
        row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            db.add(SystemSetting(key=key, value=value, is_secret=is_secret))
        else:
            row.value = value
            row.is_secret = is_secret
        updated.append(key)
    db.commit()

    # Push the new values into the running process so they take effect
    # immediately (disk thresholds, concurrency, verification, timezone).
    from app.services.runtime_settings import apply_overrides

    applied = apply_overrides(db)

    auth_svc.log_activity(db, admin, "settings.update", detail=f"Updated settings: {', '.join(updated)}",
                          ip=client_ip(request))
    return {"ok": True, "updated": updated, "applied": applied}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@router.get("/notifications/settings")
def get_notification_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("notifications:read")),
):
    ensure_default_settings(db)
    rows = db.scalars(select(NotificationSetting).order_by(NotificationSetting.event)).all()
    return [
        {**NotificationSettingOut.model_validate(r).model_dump(mode="json"),
         "label": EVENT_LABELS.get(r.event, r.event)}
        for r in rows
    ]


@router.put("/notifications/settings")
def update_notification_setting(
    payload: NotificationSettingIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = db.scalar(select(NotificationSetting).where(NotificationSetting.event == payload.event))
    if row is None:
        row = NotificationSetting(event=payload.event)
        db.add(row)
    row.in_app = payload.in_app
    row.telegram = payload.telegram
    row.email = payload.email
    row.enabled = payload.enabled
    db.commit()
    auth_svc.log_activity(db, admin, "notifications.update", detail=f"Updated notification '{payload.event}'",
                          ip=client_ip(request))
    return NotificationSettingOut.model_validate(row).model_dump(mode="json")


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = db.scalars(stmt).all()
    unread = db.scalar(select(func.count(Notification.id)).where(Notification.read.is_(False))) or 0
    return {"unread": unread, "items": [NotificationOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    for row in db.scalars(select(Notification).where(Notification.read.is_(False))).all():
        row.read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/test")
def test_notification(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from app.services.notifications import notify

    channel = (payload or {}).get("channel", "in_app")
    if channel == "telegram":
        from app.models import TelegramDestination
        from app.services.telegram_service import TelegramClient

        dest = db.scalar(select(TelegramDestination).where(TelegramDestination.enabled.is_(True)))
        if dest is None:
            raise HTTPException(status_code=400, detail="No enabled Telegram destination configured")
        try:
            TelegramClient(decrypt_secret(dest.bot_token_enc), dest.chat_id).send_message(
                "<b>Tokser Backup Manager</b>\nTest notification ✅"
            )
            return {"ok": True, "message": "Telegram test sent"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
    if channel == "email":
        from app.services.notifications import _send_email

        _send_email(db, "Test notification", "This is a test email from Tokser Backup Manager.")
        return {"ok": True, "message": "Email dispatch attempted (check logs/SMTP config)"}
    notify(db, "security_alert", "Test notification", "In-app notifications are working.", level="info")
    return {"ok": True, "message": "In-app notification created"}


# ---------------------------------------------------------------------------
# Activity logs
# ---------------------------------------------------------------------------
@router.get("/logs")
def list_logs(
    q: str = "",
    action: str = "",
    level: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("logs:read")),
):
    stmt = select(ActivityLog)
    count_stmt = select(func.count(ActivityLog.id))
    conditions = []
    if q:
        conditions.append(ActivityLog.detail.contains(q))
    if action:
        conditions.append(ActivityLog.action.startswith(action))
    if level:
        conditions.append(ActivityLog.level == level)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)).all()
    return {
        "total": total,
        "items": [ActivityOut.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.get("/logs/download")
def download_logs(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("logs:read")),
):
    from fastapi.responses import FileResponse

    log_file = Path(app_settings.log_dir) / "tokser.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(str(log_file), filename="tokser.log", media_type="text/plain")


# ---------------------------------------------------------------------------
# Health / about
# ---------------------------------------------------------------------------
@router.get("/health")
def health(db: Session = Depends(get_db)):
    from sqlalchemy import text

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "scheduler": scheduler_status(),
        "version": APP_VERSION,
        "time": utcnow().isoformat(),
    }


@router.get("/about")
def about(db: Session = Depends(get_db)):
    usage = disk_usage(app_settings.backup_dir)
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "vendor": VENDOR,
        "description": "Enterprise-grade Linux backup and recovery management platform",
        "python": os.sys.version.split()[0],
        "environment": app_settings.env,
        "database": "SQLite" if app_settings.is_sqlite else "PostgreSQL",
        "backup_dir": app_settings.backup_dir,
        "backup_disk": usage,
        "features": [
            "Unlimited backup sources per job",
            "Independent schedules per job (cron + presets)",
            "TAR / TAR.GZ / ZIP / Zstandard archives",
            "AES-256-GCM archive encryption",
            "Retention policies with automatic pruning",
            "Selective and full restore with Zip Slip protection",
            "Telegram delivery with automatic archive splitting",
            "Local, SFTP, FTP/FTPS and S3-compatible storage",
            "MySQL/MariaDB, PostgreSQL and SQLite database dumps",
            "Role-based access control and audit logging",
        ],
        "roadmap": [
            "Incremental and differential backups (metadata model ready, engine pending)",
            "Remote multi-server agents",
            "Two-factor authentication enrollment UI (verification implemented)",
        ],
    }
