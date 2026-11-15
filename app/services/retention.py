"""Retention policy enforcement.

Prunes old successful backups for a job according to ``retention_keep_last``
and ``retention_days``. Running backups and the most recent successful backup
are never removed. Source data is never touched — only archives produced by
Tokser Backup Manager.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.database import session_scope
from app.core.logging import get_logger
from app.models import BackupHistory, BackupJob, BackupStatus
from app.services.storage_backends import StorageError, build_backend
from app.core.security import decrypt_secret
from app.models import StorageDestination
from app.utils import human_bytes, utcnow

log = get_logger(__name__)


def apply_retention(job_id: int, keep_backup_id: int | None = None) -> dict:
    """Delete archives beyond the job's retention policy.

    Returns a summary dict with counts and bytes freed.
    """
    removed = 0
    freed = 0
    errors: list[str] = []

    with session_scope() as db:
        job = db.get(BackupJob, job_id)
        if job is None:
            return {"removed": 0, "freed": 0, "errors": ["Job not found"]}

        keep_last = job.retention_keep_last
        keep_days = job.retention_days
        if not keep_last and not keep_days:
            return {"removed": 0, "freed": 0, "errors": []}

        candidates = db.scalars(
            select(BackupHistory)
            .where(
                BackupHistory.job_id == job_id,
                BackupHistory.status.in_([BackupStatus.SUCCESS.value, BackupStatus.PARTIAL.value]),
            )
            .order_by(BackupHistory.started_at.desc())
        ).all()

        to_delete: list[BackupHistory] = []
        cutoff = utcnow() - timedelta(days=keep_days) if keep_days else None
        for index, history in enumerate(candidates):
            if keep_backup_id is not None and history.id == keep_backup_id:
                continue
            # Always keep the newest successful backup.
            if index == 0:
                continue
            expired_by_count = bool(keep_last) and index >= keep_last
            expired_by_age = bool(cutoff) and history.started_at is not None and _aware(history.started_at) < cutoff
            if expired_by_count or expired_by_age:
                to_delete.append(history)

        for history in to_delete:
            try:
                freed += _delete_backup_artifacts(db, history)
                db.delete(history)
                removed += 1
            except Exception as exc:
                errors.append(f"Backup {history.id}: {exc}")
                log.warning("Retention failed to delete backup %s: %s", history.id, exc)
        db.commit()

    if removed:
        log.info("Retention for job %s removed %s backup(s), freed %s", job_id, removed, human_bytes(freed))
    return {"removed": removed, "freed": freed, "errors": errors}


def _aware(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=utcnow().tzinfo)
    return dt


def _delete_backup_artifacts(db, history: BackupHistory) -> int:
    """Remove local archive and remote copy if present. Returns bytes freed."""
    freed = 0
    local_path = history.archive_path
    if local_path and os.path.isfile(local_path):
        try:
            size = os.path.getsize(local_path)
            os.unlink(local_path)
            freed += size
        except OSError as exc:
            raise RuntimeError(f"Cannot delete archive: {exc}") from exc

    # Remote copy: only delete when it lives on a non-local storage backend.
    if history.storage_destination_id and history.storage_path:
        dest = db.get(StorageDestination, history.storage_destination_id)
        if dest and dest.storage_type != "local":
            try:
                secrets = {}
                if dest.secrets_enc:
                    import json

                    secrets = json.loads(decrypt_secret(dest.secrets_enc) or "{}")
                backend = build_backend(dest.storage_type, dict(dest.config or {}), secrets)
                backend.delete(history.storage_path)
            except StorageError as exc:
                log.warning("Could not delete remote archive %s: %s", history.storage_path, exc)
    return freed
