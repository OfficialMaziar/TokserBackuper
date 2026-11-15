"""Backup execution engine.

Runs jobs in background worker threads with:
  * a global concurrency limit
  * per-job overlap prevention (a running job cannot start twice)
  * cooperative cancellation
  * live progress persisted to the database
  * archive verification, checksums and atomic finalisation
  * storage upload, Telegram delivery and retention pruning
  * notifications and activity logging

A failed run never leaves a partial archive registered as a successful backup.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.models import (
    ActivityLog,
    BackupFile,
    BackupHistory,
    BackupJob,
    BackupStatus,
    JobStatus,
    StorageDestination,
    TelegramDestination,
)
from app.services import archive as archive_svc
from app.services.db_backup import DatabaseBackupError, dump_database
from app.services.notifications import notify
from app.services.storage_backends import StorageError, build_backend
from app.services.telegram_service import TelegramClient, format_backup_report
from app.utils import disk_usage, human_bytes, safe_slug, sha256_file, utcnow

log = get_logger(__name__)

_ACTIVE_LOCK = threading.Lock()
_ACTIVE: set[int] = set()
_CANCEL: set[int] = set()
_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


class BackupError(RuntimeError):
    pass


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=max(1, settings.max_concurrent_backups),
                thread_name_prefix="tbm-backup",
            )
        return _EXECUTOR


def is_job_active(job_id: int) -> bool:
    with _ACTIVE_LOCK:
        return job_id in _ACTIVE


def active_job_ids() -> list[int]:
    with _ACTIVE_LOCK:
        return sorted(_ACTIVE)


def request_cancel(backup_id: int) -> bool:
    with _ACTIVE_LOCK:
        _CANCEL.add(backup_id)
    return True


def _cancelled(backup_id: int) -> bool:
    with _ACTIVE_LOCK:
        return backup_id in _CANCEL


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def start_job(job_id: int, trigger: str = "manual", user_id: int | None = None) -> int:
    """Queue a job run. Returns the backup history id.

    Raises BackupError if the job is missing, disabled or already running.
    """
    with session_scope() as db:
        job = db.get(BackupJob, job_id)
        if job is None:
            raise BackupError("Job not found")
        if not job.enabled:
            raise BackupError("Job is disabled")
        if is_job_active(job_id):
            raise BackupError("Job is already running")

        free = disk_usage(settings.backup_dir)["free"]
        reserve = settings.min_free_disk_mb * 1024 * 1024
        if free < reserve:
            raise BackupError(
                f"Not enough free disk space ({human_bytes(free)} available, "
                f"{settings.min_free_disk_mb} MB required)"
            )
        # Warn early when the estimated source clearly cannot fit. The estimate
        # is conservative (compression is ignored), so this only catches the
        # obvious cases; the writer still fails cleanly on a full disk.
        estimated = sum(int(s.estimated_size or 0) for s in job.sources if s.enabled)
        if estimated and estimated > max(0, free - reserve):
            raise BackupError(
                f"Estimated source size {human_bytes(estimated)} exceeds the "
                f"{human_bytes(max(0, free - reserve))} of usable free space"
            )

        history = BackupHistory(
            job_id=job.id,
            job_name=job.name,
            trigger=trigger,
            status=BackupStatus.PENDING.value,
            mode=job.backup_mode,
            source_paths=[s.path for s in job.sources if s.enabled],
            storage_destination_id=job.storage_destination_id,
        )
        db.add(history)
        db.flush()
        backup_id = history.id
        job.status = JobStatus.RUNNING.value
        job.total_runs += 1
        db.add(
            ActivityLog(
                user_id=user_id,
                username="system" if user_id is None else str(user_id),
                action="backup.start",
                entity_type="backup",
                entity_id=str(backup_id),
                detail=f"Job '{job.name}' started ({trigger})",
            )
        )

    with _ACTIVE_LOCK:
        _ACTIVE.add(job_id)
        _CANCEL.discard(backup_id)

    _executor().submit(_run_job_safe, job_id, backup_id)
    return backup_id


def _run_job_safe(job_id: int, backup_id: int) -> None:
    try:
        _run_job(job_id, backup_id)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("Unhandled backup error for job %s", job_id)
        _finalize_failure(backup_id, f"Internal error: {exc}")
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(job_id)
            _CANCEL.discard(backup_id)
        _update_next_run(job_id)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _run_job(job_id: int, backup_id: int) -> None:
    started = time.monotonic()
    started_at = utcnow()
    work_dir: Path | None = None
    archive_path: Path | None = None

    with session_scope() as db:
        history = db.get(BackupHistory, backup_id)
        job = db.get(BackupJob, job_id)
        if history is None or job is None:
            return
        history.status = BackupStatus.RUNNING.value
        history.started_at = started_at
        db.commit()

        job_name = job.name
        compression = job.compression
        level = job.compression_level
        follow = job.follow_symlinks
        preserve = job.preserve_permissions
        global_excludes = list(job.exclude_patterns or [])
        sources = [(s.path, list(s.exclude_patterns or [])) for s in job.sources if s.enabled]
        db_sources = [
            {
                "id": d.id,
                "name": d.name,
                "db_type": d.db_type,
                "host": d.host,
                "port": d.port,
                "database": d.database_name,
                "username": d.username,
                "password": decrypt_secret(d.password_enc),
                "sqlite_path": d.sqlite_path,
            }
            for d in job.database_sources
            if d.enabled
        ]
        storage_id = job.storage_destination_id
        telegram_id = job.telegram_destination_id
        telegram_upload = job.telegram_upload_enabled
        encrypt = job.encrypt_archive
        enc_password = decrypt_secret(job.encryption_password_enc) if encrypt else ""

    _notify(
        "backup_started",
        f"Backup started: {job_name}",
        f"Job '{job_name}' is running.",
        level="info",
    )

    try:
        if not sources and not db_sources:
            raise BackupError("Job has no enabled sources")

        work_dir = Path(settings.tmp_dir) / f"run_{backup_id}_{int(time.time())}"
        work_dir.mkdir(parents=True, exist_ok=True)

        # ---- collect files -------------------------------------------------
        _set_progress(backup_id, 1, "scanning")
        files, total_size = archive_svc.collect_files(
            sources,
            follow_symlinks=follow,
            global_excludes=global_excludes,
            cancel=lambda: _cancelled(backup_id),
        )

        # ---- database dumps ------------------------------------------------
        dump_files: list[tuple[Path, str]] = []
        for dsrc in db_sources:
            if _cancelled(backup_id):
                raise archive_svc.CancelledError("Cancelled")
            dump_dir = work_dir / "databases"
            try:
                result = dump_database(
                    db_type=dsrc["db_type"],
                    host=dsrc["host"],
                    port=dsrc["port"],
                    database=dsrc["database"],
                    username=dsrc["username"],
                    password=dsrc["password"],
                    sqlite_path=dsrc["sqlite_path"],
                    out_dir=dump_dir,
                    name=dsrc["name"] or dsrc["database"],
                )
                arc = f"databases/{Path(result.path).name}"
                dump_files.append((Path(result.path), arc))
                total_size += result.size
            except DatabaseBackupError as exc:
                raise BackupError(f"Database backup failed ({dsrc['name'] or dsrc['db_type']}): {exc}") from exc

        all_files = files + dump_files
        if not all_files:
            raise BackupError("No files matched the selected sources")

        # ---- create archive ------------------------------------------------
        stamp = started_at.strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_slug(job_name)}_{stamp}"
        ext = compression
        raw_archive = work_dir / f"{base_name}.{ext}"
        total_for_progress = max(total_size, 1)

        def _progress(done: int, total: int, current: str) -> None:
            if _cancelled(backup_id):
                raise archive_svc.CancelledError("Cancelled by user")
            pct = 5 + int(min(1.0, done / total_for_progress) * 80)
            _set_progress(backup_id, pct, current[:200])

        result = archive_svc.create_archive(
            all_files,
            total_size,
            raw_archive,
            fmt=compression,
            level=level,
            progress=_progress,
            cancel=lambda: _cancelled(backup_id),
            preserve_permissions=preserve,
        )
        archive_path = Path(result.path)

        # ---- encrypt -------------------------------------------------------
        if encrypt:
            if not enc_password:
                raise BackupError("Encryption is enabled but no password is configured")
            _set_progress(backup_id, 88, "encrypting")
            encrypted = work_dir / f"{base_name}.{ext}.enc"
            archive_svc.encrypt_file(archive_path, encrypted, enc_password)
            archive_path.unlink(missing_ok=True)
            archive_path = encrypted
            result.path = str(encrypted)
            result.size = encrypted.stat().st_size

        # ---- verify --------------------------------------------------------
        _set_progress(backup_id, 90, "verifying")
        verified = False
        verify_msg = "skipped"
        if settings.verify_archives:
            verified, verify_msg = archive_svc.verify_archive(
                archive_path, compression, enc_password
            )
            if not verified:
                raise BackupError(f"Archive verification failed: {verify_msg}")

        checksum = sha256_file(archive_path)
        final_size = archive_path.stat().st_size

        # ---- place in local backup directory -------------------------------
        final_dir = Path(settings.backup_dir) / safe_slug(job_name)
        final_dir.mkdir(parents=True, exist_ok=True)
        final_path = final_dir / archive_path.name
        if final_path.exists():
            final_path.unlink()
        shutil.move(str(archive_path), str(final_path))
        archive_path = final_path

        # ---- upload to storage ---------------------------------------------
        storage_path = str(final_path)
        storage_error = ""
        if storage_id:
            _set_progress(backup_id, 93, "uploading")
            try:
                storage_path = _upload_to_storage(storage_id, final_path, archive_path.name)
            except StorageError as exc:
                storage_error = str(exc)
                log.error("Storage upload failed: %s", exc)
                _notify(
                    "storage_connection_failed",
                    "Storage upload failed",
                    f"Job '{job_name}': {exc}",
                    level="error",
                )

        duration = time.monotonic() - started
        ratio = (final_size / result.source_size) if result.source_size else 0.0

        # ---- record success -------------------------------------------------
        with session_scope() as db:
            history = db.get(BackupHistory, backup_id)
            job = db.get(BackupJob, job_id)
            if history is None:
                return
            history.status = BackupStatus.SUCCESS.value
            history.finished_at = utcnow()
            history.duration_seconds = duration
            history.archive_name = archive_path.name
            history.archive_path = str(final_path)
            history.archive_size = final_size
            history.source_size = result.source_size
            history.compression_ratio = round(ratio, 4)
            history.file_count = result.file_count
            history.checksum = checksum
            history.verified = verified
            history.storage_path = storage_path
            history.progress = 95
            history.error_message = storage_error
            for entry in result.entries[:20000]:
                db.add(
                    BackupFile(
                        backup_id=backup_id,
                        path=entry.path[:2048],
                        size=entry.size,
                        mtime=entry.mtime,
                    )
                )
            if job:
                job.status = JobStatus.IDLE.value
                job.last_run_at = history.finished_at
                job.last_status = BackupStatus.SUCCESS.value
                job.last_error = storage_error
                job.success_runs += 1

        # ---- telegram -------------------------------------------------------
        if telegram_id and telegram_upload:
            _deliver_telegram(backup_id, telegram_id, job_name, archive_path, duration, started_at)

        # ---- retention ------------------------------------------------------
        _apply_retention(job_id, keep_backup_id=backup_id)

        _set_progress(backup_id, 100, "done")

        _notify(
            "backup_completed",
            f"Backup completed: {job_name}",
            f"Archive {archive_path.name} ({human_bytes(final_size)}) in {duration:.0f}s.",
            level="success",
            link=f"/backups/{backup_id}",
        )
        _log_activity("backup.complete", backup_id, f"Job '{job_name}' succeeded ({human_bytes(final_size)})")

    except archive_svc.CancelledError:
        _finalize_failure(backup_id, "Cancelled by user", status=BackupStatus.CANCELLED.value)
        _log_activity("backup.cancel", backup_id, f"Job '{job_name}' cancelled")
    except (BackupError, archive_svc.ArchiveError, OSError, ValueError) as exc:
        log.error("Backup %s failed: %s", backup_id, exc)
        _finalize_failure(backup_id, str(exc))
        _notify(
            "backup_failed",
            f"Backup failed: {job_name}",
            str(exc)[:1000],
            level="error",
            link=f"/backups/{backup_id}",
        )
    except Exception as exc:  # pragma: no cover - unexpected
        log.error("Backup %s crashed: %s\n%s", backup_id, exc, traceback.format_exc())
        _finalize_failure(backup_id, f"Unexpected error: {exc}")
    finally:
        if work_dir and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def _notify(event: str, title: str, message: str, **kwargs) -> None:
    """Dispatch a notification in its own short-lived transaction."""
    try:
        with session_scope() as db:
            notify(db, event, title, message, **kwargs)
    except Exception:
        log.warning("Notification dispatch failed for %s", event, exc_info=True)


def _set_progress(backup_id: int, pct: int, stage: str) -> None:
    try:
        with session_scope() as db:
            history = db.get(BackupHistory, backup_id)
            if history is None:
                return
            history.progress = max(0, min(100, pct))
    except Exception:
        log.debug("Progress update failed for %s", backup_id, exc_info=True)


def _finalize_failure(backup_id: int, message: str, status: str = BackupStatus.FAILED.value) -> None:
    with session_scope() as db:
        history = db.get(BackupHistory, backup_id)
        if history is None:
            return
        history.status = status
        history.finished_at = utcnow()
        history.error_message = message[:4000]
        if history.started_at:
            started = history.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            history.duration_seconds = (utcnow() - started).total_seconds()
        job = db.get(BackupJob, history.job_id) if history.job_id else None
        if job:
            job.status = JobStatus.IDLE.value
            job.last_run_at = history.finished_at
            job.last_status = status
            job.last_error = message[:4000]
            job.failed_runs += 1
        # Remove any partial archive that may have been recorded.
        if history.archive_path and os.path.exists(history.archive_path):
            try:
                os.unlink(history.archive_path)
            except OSError:
                pass


def _upload_to_storage(storage_id: int, local_path: Path, remote_name: str) -> str:
    with session_scope() as db:
        dest = db.get(StorageDestination, storage_id)
        if dest is None:
            raise StorageError("Storage destination not found")
        secrets = {}
        if dest.secrets_enc:
            import json

            try:
                secrets = json.loads(decrypt_secret(dest.secrets_enc) or "{}")
            except Exception:
                secrets = {}
        backend = build_backend(dest.storage_type, dict(dest.config or {}), secrets)
    return backend.upload(str(local_path), remote_name)


def _deliver_telegram(backup_id: int, telegram_id: int, job_name: str, archive_path: Path,
                      duration: float, started_at: datetime) -> None:
    with session_scope() as db:
        dest = db.get(TelegramDestination, telegram_id)
        if dest is None or not dest.enabled:
            return
        token = decrypt_secret(dest.bot_token_enc)
        chat_id = dest.chat_id

    if not token or not chat_id:
        _record_telegram(backup_id, "not_configured", 0, 0)
        return

    client = TelegramClient(token, chat_id)
    caption = format_backup_report(
        status="success",
        job_name=job_name,
        archive_name=archive_path.name,
        archive_size=archive_path.stat().st_size,
        duration=duration,
        started_at=started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
    try:
        result = client.send_document(str(archive_path), caption)
        status = "sent" if result.ok else "partial" if result.parts_sent else "failed"
        _record_telegram(backup_id, status, result.parts_total, result.parts_sent)
        if not result.ok:
            log.error("Telegram delivery incomplete: %s", result.message)
    except Exception as exc:
        log.error("Telegram delivery failed: %s", exc)
        _record_telegram(backup_id, "failed", 0, 0)


def _record_telegram(backup_id: int, status: str, parts: int, sent: int) -> None:
    with session_scope() as db:
        history = db.get(BackupHistory, backup_id)
        if history:
            history.telegram_status = status
            history.telegram_parts = parts
            history.telegram_parts_sent = sent


def _apply_retention(job_id: int, keep_backup_id: int | None = None) -> None:
    from app.services.retention import apply_retention

    try:
        apply_retention(job_id, keep_backup_id=keep_backup_id)
    except Exception:
        log.exception("Retention pruning failed for job %s", job_id)


def _log_activity(action: str, backup_id: int, detail: str) -> None:
    with session_scope() as db:
        db.add(
            ActivityLog(
                username="system",
                action=action,
                entity_type="backup",
                entity_id=str(backup_id),
                detail=detail,
                level="info",
            )
        )


def _update_next_run(job_id: int) -> None:
    from app.services.scheduler import recalculate_job_next_run

    try:
        recalculate_job_next_run(job_id)
    except Exception:
        log.debug("Next-run recalculation failed", exc_info=True)
