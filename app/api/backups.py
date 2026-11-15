"""Backup history, detail, download, archive browsing, deletion and restore."""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, require_permission
from app.core.database import get_db
from app.core.security import decrypt_secret
from app.models import BackupHistory, BackupJob, RestoreHistory, User
from app.schemas import BackupFileOut, BackupOut, RestoreOut, RestoreRequest
from app.services import archive as archive_svc
from app.services import auth as auth_svc
from app.services.backup_engine import request_cancel
from app.services.restore_engine import RestoreError, start_restore

router = APIRouter(prefix="/api/v1/backups", tags=["backups"])

# Restore history lives on its own prefix ("/api/v1/restores") so the static
# "list" path can never be captured by the "/{backup_id}" route.
restore_router = APIRouter(prefix="/api/v1/restores", tags=["restores"])


def _get_backup(db: Session, backup_id: int) -> BackupHistory:
    backup = db.get(BackupHistory, backup_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return backup


def _fmt(backup: BackupHistory, job: BackupJob | None) -> str:
    name = (backup.archive_name or "").lower()
    if name.endswith(".enc"):
        name = name[:-4]
    for fmt in ("tar.gz", "tar", "zip", "zst"):
        if name.endswith("." + fmt):
            return fmt
    return job.compression if job else "tar.gz"


@router.get("")
def list_backups(
    job_id: int | None = None,
    status: str | None = None,
    q: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    stmt = select(BackupHistory)
    count_stmt = select(func.count(BackupHistory.id))
    conditions = []
    if job_id:
        conditions.append(BackupHistory.job_id == job_id)
    if status:
        conditions.append(BackupHistory.status == status)
    if q:
        conditions.append(func.lower(BackupHistory.job_name).contains(q.lower()))
    if date_from:
        try:
            conditions.append(BackupHistory.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            conditions.append(BackupHistory.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(BackupHistory.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "total": total,
        "items": [BackupOut.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.get("/export")
def export_backups(
    format: str = "csv",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    rows = db.scalars(select(BackupHistory).order_by(BackupHistory.created_at.desc()).limit(10000)).all()
    data = [BackupOut.model_validate(r).model_dump(mode="json") for r in rows]
    if format == "json":
        payload = json.dumps(data, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(payload.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=backups.json"},
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    fields = ["id", "job_name", "status", "mode", "started_at", "finished_at", "duration_seconds",
              "archive_name", "archive_size", "file_count", "verified", "telegram_status", "error_message"]
    writer.writerow(fields)
    for item in data:
        writer.writerow([item.get(f, "") for f in fields])
    return StreamingResponse(
        io.BytesIO(buffer.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=backups.csv"},
    )


@router.get("/{backup_id}")
def get_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    backup = _get_backup(db, backup_id)
    data = BackupOut.model_validate(backup).model_dump(mode="json")
    job = db.get(BackupJob, backup.job_id) if backup.job_id else None
    data["archive_format"] = _fmt(backup, job)
    data["archive_exists"] = bool(backup.archive_path and os.path.isfile(backup.archive_path))
    data["encrypted"] = bool(job and job.encrypt_archive)
    return data


@router.get("/{backup_id}/files")
def backup_files(
    backup_id: int,
    q: str = "",
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    backup = _get_backup(db, backup_id)
    from app.models import BackupFile

    stmt = select(BackupFile).where(BackupFile.backup_id == backup_id)
    if q:
        stmt = stmt.where(BackupFile.path.contains(q))
    rows = db.scalars(stmt.order_by(BackupFile.path).limit(limit).offset(offset)).all()
    total = db.scalar(
        select(func.count(BackupFile.id)).where(BackupFile.backup_id == backup_id)
    ) or 0
    return {
        "total": total,
        "items": [BackupFileOut.model_validate(r).model_dump(mode="json") for r in rows],
        "archive_available": bool(backup.archive_path and os.path.isfile(backup.archive_path)),
    }


@router.get("/{backup_id}/archive")
def browse_archive(
    backup_id: int,
    q: str = "",
    limit: int = Query(default=1000, ge=1, le=20000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    """List the real contents of the archive on disk (not just metadata)."""
    backup = _get_backup(db, backup_id)
    if not backup.archive_path or not os.path.isfile(backup.archive_path):
        raise HTTPException(status_code=404, detail="Archive file is no longer on disk")
    job = db.get(BackupJob, backup.job_id) if backup.job_id else None
    fmt = _fmt(backup, job)
    password = decrypt_secret(job.encryption_password_enc) if job and job.encrypt_archive else ""
    try:
        entries = archive_svc.list_archive(backup.archive_path, fmt, password)
    except archive_svc.ArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if q:
        entries = [e for e in entries if q.lower() in e.path.lower()]
    total = len(entries)
    return {
        "total": total,
        "truncated": total > limit,
        "items": [
            {"path": e.path, "size": e.size, "mtime": e.mtime, "is_dir": e.is_dir}
            for e in entries[:limit]
        ],
    }


@router.post("/{backup_id}/verify")
def verify_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    backup = _get_backup(db, backup_id)
    if not backup.archive_path or not os.path.isfile(backup.archive_path):
        raise HTTPException(status_code=404, detail="Archive file is no longer on disk")
    job = db.get(BackupJob, backup.job_id) if backup.job_id else None
    fmt = _fmt(backup, job)
    password = decrypt_secret(job.encryption_password_enc) if job and job.encrypt_archive else ""
    ok, message = archive_svc.verify_archive(backup.archive_path, fmt, password)
    backup.verified = ok
    db.commit()
    return {"ok": ok, "message": message}


@router.get("/{backup_id}/download")
def download_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    backup = _get_backup(db, backup_id)
    if not backup.archive_path or not os.path.isfile(backup.archive_path):
        raise HTTPException(status_code=404, detail="Archive file is no longer on disk")
    return FileResponse(
        backup.archive_path,
        filename=backup.archive_name or os.path.basename(backup.archive_path),
        media_type="application/octet-stream",
    )


@router.post("/{backup_id}/cancel")
def cancel_backup(
    backup_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:write")),
):
    backup = _get_backup(db, backup_id)
    if backup.status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Backup is not running")
    backup.cancel_requested = True
    db.commit()
    request_cancel(backup_id)
    auth_svc.log_activity(db, user, "backup.cancel_request", entity_type="backup",
                          entity_id=str(backup_id), detail="Cancellation requested",
                          ip=client_ip(request))
    return {"ok": True}


@router.delete("/{backup_id}")
def delete_backup(
    backup_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:delete")),
):
    backup = _get_backup(db, backup_id)
    if backup.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running backup")
    freed = 0
    if backup.archive_path and os.path.isfile(backup.archive_path):
        try:
            freed = os.path.getsize(backup.archive_path)
            os.unlink(backup.archive_path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Cannot delete archive: {exc}") from exc
    db.delete(backup)
    db.commit()
    auth_svc.log_activity(db, user, "backup.delete", entity_type="backup", entity_id=str(backup_id),
                          detail=f"Deleted backup and freed {freed} bytes", ip=client_ip(request))
    return {"ok": True, "freed": freed}


@router.post("/{backup_id}/restore")
def restore_backup(
    backup_id: int,
    payload: RestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:restore")),
):
    try:
        restore_id = start_restore(
            backup_id,
            payload.destination,
            selected_paths=payload.selected_paths,
            overwrite=payload.overwrite,
            create_safety_backup=payload.create_safety_backup,
            preserve_permissions=payload.preserve_permissions,
            user_id=user.id,
        )
    except RestoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    auth_svc.log_activity(db, user, "restore.start", entity_type="restore", entity_id=str(restore_id),
                          detail=f"Restore of backup #{backup_id} to {payload.destination}",
                          ip=client_ip(request))
    return {"ok": True, "restore_id": restore_id}


@restore_router.get("")
def list_restores(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    rows = db.scalars(select(RestoreHistory).order_by(RestoreHistory.created_at.desc()).limit(limit)).all()
    return [RestoreOut.model_validate(r).model_dump(mode="json") for r in rows]


@restore_router.get("/{restore_id}")
def get_restore(
    restore_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backups:read")),
):
    row = db.get(RestoreHistory, restore_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Restore not found")
    data = RestoreOut.model_validate(row).model_dump(mode="json")
    data["progress"] = row.progress
    data["current_path"] = row.current_path
    data["safety_backup_path"] = row.safety_backup_path
    return data
