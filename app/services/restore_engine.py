"""Restore execution.

Restores run in a background thread, update ``restore_history`` live and
optionally create a safety backup of the destination before overwriting.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.models import (
    ActivityLog,
    BackupHistory,
    BackupJob,
    RestoreHistory,
    RestoreStatus,
)
from app.services import archive as archive_svc
from app.services.notifications import notify
from app.utils import utcnow

log = get_logger(__name__)

_RUNNING: set[int] = set()
_LOCK = threading.Lock()


class RestoreError(RuntimeError):
    pass


def start_restore(
    backup_id: int,
    destination: str,
    selected_paths: list[str] | None = None,
    overwrite: bool = False,
    create_safety_backup: bool = True,
    preserve_permissions: bool = True,
    user_id: int | None = None,
) -> int:
    with session_scope() as db:
        backup = db.get(BackupHistory, backup_id)
        if backup is None:
            raise RestoreError("Backup not found")
        if backup.status not in {"success", "partial"}:
            raise RestoreError("Only successful backups can be restored")
        if not backup.archive_path or not Path(backup.archive_path).exists():
            raise RestoreError("Archive file is missing from disk")

        dest = Path(destination)
        if not dest.is_absolute():
            raise RestoreError("Destination must be an absolute path")

        record = RestoreHistory(
            backup_id=backup_id,
            user_id=user_id,
            status=RestoreStatus.PENDING.value,
            destination=str(dest),
            selected_paths=list(selected_paths or []),
            overwrite=overwrite,
        )
        db.add(record)
        db.flush()
        restore_id = record.id

    thread = threading.Thread(
        target=_run_restore,
        args=(restore_id, backup_id, str(dest), list(selected_paths or []), overwrite,
              create_safety_backup, preserve_permissions),
        name=f"tbm-restore-{restore_id}",
        daemon=True,
    )
    thread.start()
    return restore_id


def _archive_format(backup: BackupHistory, job: BackupJob | None) -> str:
    name = (backup.archive_name or "").lower()
    if name.endswith(".enc"):
        name = name[:-4]
    for fmt in ("tar.gz", "tar", "zip", "zst"):
        if name.endswith("." + fmt):
            return fmt
    if job:
        return job.compression
    return "tar.gz"


def _run_restore(restore_id, backup_id, destination, selected, overwrite,
                 create_safety_backup, preserve_permissions) -> None:
    started = time.monotonic()
    with _LOCK:
        _RUNNING.add(restore_id)
    try:
        with session_scope() as db:
            record = db.get(RestoreHistory, restore_id)
            backup = db.get(BackupHistory, backup_id)
            if record is None or backup is None:
                return
            record.status = RestoreStatus.RUNNING.value
            record.started_at = utcnow()
            db.commit()

            archive_path = backup.archive_path
            job = db.get(BackupJob, backup.job_id) if backup.job_id else None
            fmt = _archive_format(backup, job)
            enc_password = ""
            if job and job.encrypt_archive:
                enc_password = decrypt_secret(job.encryption_password_enc)

        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)

        if create_safety_backup and any(dest.iterdir()):
            # Records the archive path on the restore row; failures are logged
            # and never block the restore itself.
            _create_safety_backup(dest, restore_id)

        def _progress(done, total, current):
            pct = min(99, int(done / max(total, 1) * 100))
            with session_scope() as db:
                rec = db.get(RestoreHistory, restore_id)
                if rec:
                    rec.restored_bytes = done
                    rec.progress = pct
                    rec.current_path = (current or "")[:2048]
                    rec.status = RestoreStatus.RUNNING.value

        files, size = archive_svc.extract_archive(
            archive_path,
            fmt,
            dest,
            selected_paths=selected,
            overwrite=overwrite,
            preserve_permissions=preserve_permissions,
            password=enc_password,
            progress=_progress,
        )

        duration = time.monotonic() - started
        with session_scope() as db:
            record = db.get(RestoreHistory, restore_id)
            if record:
                record.status = RestoreStatus.SUCCESS.value
                record.finished_at = utcnow()
                record.restored_files = files
                record.restored_bytes = size
                record.progress = 100
                record.current_path = ""
                record.error_message = ""
            db.add(
                ActivityLog(
                    user_id=record.user_id if record else None,
                    username="system",
                    action="restore.complete",
                    entity_type="restore",
                    entity_id=str(restore_id),
                    detail=f"Restored {files} file(s) to {dest} in {duration:.0f}s",
                )
            )

        with session_scope() as db:
            notify(
                db, "restore_completed",
                "Restore completed",
                f"{files} file(s) restored to {dest}.",
                level="success",
                link=f"/backups/{backup_id}",
            )
    except Exception as exc:
        log.exception("Restore %s failed", restore_id)
        with session_scope() as db:
            record = db.get(RestoreHistory, restore_id)
            if record:
                record.status = RestoreStatus.FAILED.value
                record.finished_at = utcnow()
                record.error_message = str(exc)[:4000]
    finally:
        with _LOCK:
            _RUNNING.discard(restore_id)


def _create_safety_backup(dest: Path, restore_id: int) -> str | None:
    """Archive the destination before overwriting it.

    Returns the archive path, or None when there was nothing to archive or the
    operation failed (logged, never fatal to the restore).
    """
    try:
        files, total = archive_svc.collect_files([(str(dest), [])])
        if not files:
            return None
        out_dir = Path(settings.backup_dir) / "_safety"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"safety_restore{restore_id}_{utcnow().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        result = archive_svc.create_archive(files, total, out_dir / name, fmt="tar.gz", level=6)
        with session_scope() as db:
            record = db.get(RestoreHistory, restore_id)
            if record:
                record.safety_backup_path = result.path
            db.add(
                ActivityLog(
                    username="system",
                    action="restore.safety_backup",
                    entity_type="restore",
                    entity_id=str(restore_id),
                    detail=f"Safety archive created: {result.path}",
                )
            )
        return result.path
    except Exception as exc:
        log.warning("Safety backup failed: %s", exc)
        return None


def is_running(restore_id: int) -> bool:
    with _LOCK:
        return restore_id in _RUNNING
