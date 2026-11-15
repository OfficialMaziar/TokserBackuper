"""Notification dispatch (in-app, Telegram, email)."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.models import Notification, NotificationSetting, SystemSetting, TelegramDestination
from app.services.telegram_service import TelegramClient, TelegramError

log = get_logger(__name__)

EVENTS = [
    "backup_started",
    "backup_completed",
    "backup_failed",
    "restore_completed",
    "low_disk_space",
    "storage_connection_failed",
    "scheduler_error",
    "security_alert",
]

EVENT_LABELS = {
    "backup_started": "Backup started",
    "backup_completed": "Backup completed",
    "backup_failed": "Backup failed",
    "restore_completed": "Restore completed",
    "low_disk_space": "Low disk space",
    "storage_connection_failed": "Storage connection failed",
    "scheduler_error": "Scheduler error",
    "security_alert": "Security alert",
}


def ensure_default_settings(db: Session) -> None:
    existing = {s.event for s in db.scalars(select(NotificationSetting)).all()}
    for event in EVENTS:
        if event not in existing:
            db.add(
                NotificationSetting(
                    event=event,
                    in_app=True,
                    telegram=event in {"backup_failed", "low_disk_space", "security_alert"},
                    email=False,
                    enabled=True,
                )
            )
    db.commit()


def _get_setting(db: Session, event: str) -> NotificationSetting | None:
    return db.scalar(select(NotificationSetting).where(NotificationSetting.event == event))


def _smtp_config(db: Session) -> dict:
    rows = db.scalars(
        select(SystemSetting).where(SystemSetting.key.like("smtp_%"))
    ).all()
    cfg: dict[str, str] = {}
    for row in rows:
        if row.is_secret or row.key == "smtp_password":
            cfg["smtp_password"] = decrypt_secret(row.value)
        else:
            cfg[row.key] = row.value
    return cfg


def notify(
    db: Session,
    event: str,
    title: str,
    message: str,
    *,
    level: str = "info",
    link: str = "",
    telegram_text: str | None = None,
    user_id: int | None = None,
) -> None:
    """Create an in-app notification and fan out to enabled channels.

    Channel failures are logged but never break the caller (a backup must not
    fail because Telegram is down); the failure itself is recorded in logs.
    """
    setting = _get_setting(db, event)
    if setting is not None and not setting.enabled:
        return

    in_app = setting.in_app if setting else True
    want_telegram = setting.telegram if setting else False
    want_email = setting.email if setting else False

    if in_app:
        db.add(
            Notification(
                event=event,
                level=level,
                title=title[:255],
                message=message,
                link=link,
                user_id=user_id,
            )
        )
        db.commit()

    if want_telegram:
        _send_telegram(db, telegram_text or f"<b>{title}</b>\n{message}")

    if want_email:
        _send_email(db, title, message)


def _send_telegram(db: Session, text: str) -> None:
    destinations = db.scalars(
        select(TelegramDestination).where(
            TelegramDestination.enabled.is_(True),
            TelegramDestination.send_notifications.is_(True),
        )
    ).all()
    for dest in destinations:
        token = decrypt_secret(dest.bot_token_enc)
        if not token or not dest.chat_id:
            continue
        try:
            TelegramClient(token, dest.chat_id).send_message(text)
        except TelegramError as exc:
            log.warning("Telegram notification to %s failed: %s", dest.name, exc)
        except Exception as exc:  # pragma: no cover - network
            log.warning("Telegram notification error: %s", exc)


def _send_email(db: Session, subject: str, body: str) -> None:
    cfg = _smtp_config(db)
    host = cfg.get("smtp_host")
    to_addr = cfg.get("smtp_to")
    if not host or not to_addr:
        return
    msg = EmailMessage()
    msg["Subject"] = f"[Tokser Backup Manager] {subject}"
    msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_username") or "tbm@localhost"
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        port = int(cfg.get("smtp_port") or 587)
        use_tls = str(cfg.get("smtp_tls", "true")).lower() in {"1", "true", "yes"}
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if cfg.get("smtp_username"):
                smtp.login(cfg["smtp_username"], cfg.get("smtp_password", ""))
            smtp.send_message(msg)
    except Exception as exc:
        log.warning("Email notification failed: %s", exc)
