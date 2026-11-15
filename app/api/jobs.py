"""Backup job CRUD, control and source management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, require_permission
from app.core.database import get_db
from app.core.security import encrypt_secret
from app.models import (
    BackupJob,
    BackupSource,
    DatabaseSource,
    JobStatus,
    Schedule,
    User,
)
from app.schemas import (
    DatabaseSourceOut,
    JobIn,
    JobOut,
    ScheduleOut,
    SourceIn,
    SourceOut,
)
from app.services import auth as auth_svc
from app.services.backup_engine import BackupError, is_job_active, start_job
from app.services.cron import describe_schedule
from app.services.scheduler import compute_job_next_run
from app.utils import dir_size, utcnow

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _serialize(job: BackupJob) -> dict:
    data = JobOut.model_validate(job).model_dump(mode="json")
    data["running"] = is_job_active(job.id)
    data["schedule_description"] = (
        describe_schedule(
            job.schedule.schedule_type,
            interval_value=job.schedule.interval_value,
            hour=job.schedule.hour,
            minute=job.schedule.minute,
            day_of_week=job.schedule.day_of_week,
            day_of_month=job.schedule.day_of_month,
            cron_expression=job.schedule.cron_expression,
        )
        if job.schedule
        else "Manual only"
    )
    return data


def _apply_sources(db: Session, job: BackupJob, sources_in: list[SourceIn]) -> None:
    existing = {s.path: s for s in job.sources}
    keep: set[str] = set()
    for src in sources_in:
        keep.add(src.path)
        if src.path in existing:
            obj = existing[src.path]
            obj.name = src.name
            obj.enabled = src.enabled
            obj.exclude_patterns = src.exclude_patterns
        else:
            db.add(
                BackupSource(
                    job_id=job.id,
                    name=src.name,
                    path=src.path,
                    enabled=src.enabled,
                    exclude_patterns=src.exclude_patterns,
                )
            )
    for path, obj in existing.items():
        if path not in keep:
            db.delete(obj)


def _apply_databases(db: Session, job: BackupJob, items) -> None:
    """Reconcile database sources against the submitted list.

    Matching is position-based rather than name-based: a rename or a blank
    name would otherwise create a duplicate row on every save, and blank
    names are legitimate. Existing rows are reused in place so a stored
    password survives when the field is submitted empty.
    """
    existing = sorted(job.database_sources, key=lambda d: d.id)
    for index, item in enumerate(items):
        if index < len(existing):
            obj = existing[index]
        else:
            obj = DatabaseSource(job_id=job.id)
            db.add(obj)
        obj.name = item.name
        obj.db_type = item.db_type.value
        obj.host = item.host
        obj.port = item.port
        obj.database_name = item.database_name
        obj.username = item.username
        obj.sqlite_path = item.sqlite_path
        obj.enabled = item.enabled
        # An empty password means "keep the stored one".
        if item.password:
            obj.password_enc = encrypt_secret(item.password)
    for surplus in existing[len(items):]:
        db.delete(surplus)


def _apply_schedule(db: Session, job: BackupJob, sched_in) -> None:
    if sched_in is None:
        if job.schedule:
            db.delete(job.schedule)
        return
    sched = job.schedule or Schedule(job_id=job.id)
    if job.schedule is None:
        db.add(sched)
    sched.schedule_type = sched_in.schedule_type.value
    sched.interval_value = sched_in.interval_value
    sched.hour = sched_in.hour
    sched.minute = sched_in.minute
    sched.day_of_week = sched_in.day_of_week
    sched.day_of_month = sched_in.day_of_month
    sched.cron_expression = sched_in.cron_expression
    sched.timezone = sched_in.timezone
    sched.start_date = sched_in.start_date
    sched.end_date = sched_in.end_date
    sched.paused = sched_in.paused


@router.get("")
def list_jobs(
    q: str = "",
    enabled: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:read")),
):
    stmt = select(BackupJob).order_by(BackupJob.created_at.desc())
    if q:
        stmt = stmt.where(func.lower(BackupJob.name).contains(q.lower()))
    if enabled is not None:
        stmt = stmt.where(BackupJob.enabled.is_(enabled))
    jobs = db.scalars(stmt).all()
    return [_serialize(j) for j in jobs]


@router.post("")
def create_job(
    payload: JobIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    if db.scalar(select(BackupJob).where(func.lower(BackupJob.name) == payload.name.lower())):
        raise HTTPException(status_code=409, detail="A job with this name already exists")
    if not payload.sources and not payload.database_sources:
        raise HTTPException(status_code=400, detail="Add at least one source or database")
    if payload.encrypt_archive and not payload.encryption_password:
        raise HTTPException(
            status_code=400,
            detail="An encryption password is required when encryption is enabled",
        )

    job = BackupJob(
        name=payload.name.strip(),
        description=payload.description,
        enabled=payload.enabled,
        compression=payload.compression,
        compression_level=payload.compression_level,
        backup_mode=payload.backup_mode.value,
        storage_destination_id=payload.storage_destination_id,
        telegram_destination_id=payload.telegram_destination_id,
        telegram_upload_enabled=payload.telegram_upload_enabled,
        retention_keep_last=payload.retention_keep_last,
        retention_days=payload.retention_days,
        encrypt_archive=payload.encrypt_archive,
        encryption_password_enc=encrypt_secret(payload.encryption_password) if payload.encryption_password else "",
        follow_symlinks=payload.follow_symlinks,
        preserve_permissions=payload.preserve_permissions,
        exclude_patterns=payload.exclude_patterns,
        status=JobStatus.IDLE.value,
    )
    db.add(job)
    db.flush()
    _apply_sources(db, job, payload.sources)
    _apply_databases(db, job, payload.database_sources)
    _apply_schedule(db, job, payload.schedule)
    db.commit()
    db.refresh(job)
    job.next_run_at = compute_job_next_run(job)
    db.commit()
    auth_svc.log_activity(db, user, "job.create", entity_type="job", entity_id=str(job.id),
                          detail=f"Created job '{job.name}'", ip=client_ip(request))
    return _serialize(job)


@router.get("/{job_id}")
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:read")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize(job)


@router.put("/{job_id}")
def update_job(
    job_id: int,
    payload: JobIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    duplicate = db.scalar(
        select(BackupJob).where(func.lower(BackupJob.name) == payload.name.lower(), BackupJob.id != job_id)
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A job with this name already exists")
    if not payload.sources and not payload.database_sources:
        raise HTTPException(status_code=400, detail="Add at least one source or database")

    job.name = payload.name.strip()
    job.description = payload.description
    job.enabled = payload.enabled
    job.compression = payload.compression
    job.compression_level = payload.compression_level
    job.backup_mode = payload.backup_mode.value
    job.storage_destination_id = payload.storage_destination_id
    job.telegram_destination_id = payload.telegram_destination_id
    job.telegram_upload_enabled = payload.telegram_upload_enabled
    job.retention_keep_last = payload.retention_keep_last
    job.retention_days = payload.retention_days
    job.encrypt_archive = payload.encrypt_archive
    if payload.encryption_password:
        job.encryption_password_enc = encrypt_secret(payload.encryption_password)
    elif payload.encrypt_archive and not job.encryption_password_enc:
        # Refuse to save an encrypted job that has no password: it would fail
        # only at run time, long after the operator left the form.
        raise HTTPException(
            status_code=400,
            detail="An encryption password is required when encryption is enabled",
        )
    job.follow_symlinks = payload.follow_symlinks
    job.preserve_permissions = payload.preserve_permissions
    job.exclude_patterns = payload.exclude_patterns

    _apply_sources(db, job, payload.sources)
    _apply_databases(db, job, payload.database_sources)
    _apply_schedule(db, job, payload.schedule)
    db.commit()
    db.refresh(job)
    job.next_run_at = compute_job_next_run(job)
    db.commit()
    auth_svc.log_activity(db, user, "job.update", entity_type="job", entity_id=str(job.id),
                          detail=f"Updated job '{job.name}'", ip=client_ip(request))
    return _serialize(job)


@router.delete("/{job_id}")
def delete_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if is_job_active(job_id):
        raise HTTPException(status_code=409, detail="Cannot delete a running job")
    name = job.name
    db.delete(job)
    db.commit()
    auth_svc.log_activity(db, user, "job.delete", entity_type="job", entity_id=str(job_id),
                          detail=f"Deleted job '{name}'", ip=client_ip(request))
    return {"ok": True}


@router.post("/{job_id}/duplicate")
def duplicate_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    base_name = f"{job.name} (copy)"
    name = base_name
    counter = 2
    while db.scalar(select(BackupJob).where(BackupJob.name == name)):
        name = f"{base_name} {counter}"
        counter += 1

    clone = BackupJob(
        name=name,
        description=job.description,
        enabled=False,
        compression=job.compression,
        compression_level=job.compression_level,
        backup_mode=job.backup_mode,
        storage_destination_id=job.storage_destination_id,
        telegram_destination_id=job.telegram_destination_id,
        telegram_upload_enabled=job.telegram_upload_enabled,
        retention_keep_last=job.retention_keep_last,
        retention_days=job.retention_days,
        encrypt_archive=job.encrypt_archive,
        encryption_password_enc=job.encryption_password_enc,
        follow_symlinks=job.follow_symlinks,
        preserve_permissions=job.preserve_permissions,
        exclude_patterns=list(job.exclude_patterns or []),
        status=JobStatus.IDLE.value,
    )
    db.add(clone)
    db.flush()
    for s in job.sources:
        db.add(BackupSource(job_id=clone.id, name=s.name, path=s.path, enabled=s.enabled,
                            exclude_patterns=list(s.exclude_patterns or [])))
    for d in job.database_sources:
        db.add(DatabaseSource(job_id=clone.id, name=d.name, db_type=d.db_type, host=d.host,
                              port=d.port, database_name=d.database_name, username=d.username,
                              password_enc=d.password_enc, sqlite_path=d.sqlite_path, enabled=d.enabled))
    if job.schedule:
        s = job.schedule
        db.add(Schedule(job_id=clone.id, schedule_type=s.schedule_type, interval_value=s.interval_value,
                        hour=s.hour, minute=s.minute, day_of_week=s.day_of_week,
                        day_of_month=s.day_of_month, cron_expression=s.cron_expression,
                        timezone=s.timezone, paused=True))
    db.commit()
    db.refresh(clone)
    auth_svc.log_activity(db, user, "job.duplicate", entity_type="job", entity_id=str(clone.id),
                          detail=f"Duplicated job '{job.name}' as '{name}'", ip=client_ip(request))
    return _serialize(clone)


@router.post("/{job_id}/run")
def run_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:run")),
):
    try:
        backup_id = start_job(job_id, trigger="manual", user_id=user.id)
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    auth_svc.log_activity(db, user, "job.run", entity_type="job", entity_id=str(job_id),
                          detail=f"Manual run started (backup #{backup_id})", ip=client_ip(request))
    return {"ok": True, "backup_id": backup_id}


@router.post("/{job_id}/pause")
def pause_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.schedule:
        job.schedule.paused = True
    job.status = JobStatus.PAUSED.value
    job.next_run_at = None
    db.commit()
    auth_svc.log_activity(db, user, "job.pause", entity_type="job", entity_id=str(job_id),
                          detail=f"Paused job '{job.name}'", ip=client_ip(request))
    return _serialize(job)


@router.post("/{job_id}/resume")
def resume_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.schedule:
        job.schedule.paused = False
    job.status = JobStatus.IDLE.value
    job.next_run_at = compute_job_next_run(job)
    db.commit()
    auth_svc.log_activity(db, user, "job.resume", entity_type="job", entity_id=str(job_id),
                          detail=f"Resumed job '{job.name}'", ip=client_ip(request))
    return _serialize(job)


@router.post("/{job_id}/toggle")
def toggle_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("jobs:write")),
):
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.enabled = not job.enabled
    job.status = JobStatus.IDLE.value if job.enabled else JobStatus.DISABLED.value
    job.next_run_at = compute_job_next_run(job)
    db.commit()
    auth_svc.log_activity(db, user, "job.toggle", entity_type="job", entity_id=str(job_id),
                          detail=f"{'Enabled' if job.enabled else 'Disabled'} job '{job.name}'",
                          ip=client_ip(request))
    return _serialize(job)


# ---------------------------------------------------------------------------
# Source helpers (browse / estimate / validate)
# ---------------------------------------------------------------------------
sources_router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@sources_router.get("/browse")
def browse(
    path: str = "/",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sources:read")),
):
    import os
    import string
    from pathlib import Path

    raw = (path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")

    p = Path(raw)
    # A bare "/" is not an absolute path on Windows, where the filesystem is
    # rooted at a drive. Treat it as a request to list the available drives
    # instead of rejecting it, so the browser has a valid starting point.
    if os.name == "nt" and raw in {"/", "\\"}:
        drives = [
            {"name": f"{d}:\\", "path": f"{d}:\\", "is_dir": True, "size": 0}
            for d in string.ascii_uppercase
            if Path(f"{d}:\\").exists()
        ]
        return {"path": "", "parent": None, "entries": drives, "drives": True}

    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    entries = []
    try:
        with os.scandir(p) as it:
            for entry in it:
                if entry.name.startswith(".") and entry.name not in {".config", ".ssh"}:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                entries.append({"name": entry.name, "path": entry.path, "is_dir": is_dir, "size": size})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied") from exc
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    parent = str(p.parent) if str(p.parent) != str(p) else None
    return {"path": str(p), "parent": parent, "entries": entries[:2000]}


@sources_router.post("/validate")
def validate_source(
    payload: SourceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sources:read")),
):
    import os
    from pathlib import Path

    p = Path(payload.path)
    result = {"path": payload.path, "exists": p.exists(), "readable": False,
              "is_dir": p.is_dir() if p.exists() else False, "size": 0, "message": ""}
    if not p.exists():
        result["message"] = "Path does not exist"
        return result
    result["readable"] = os.access(p, os.R_OK)
    if not result["readable"]:
        result["message"] = "Permission denied (service user cannot read this path)"
    result["size"] = dir_size(p, limit_seconds=3.0)
    return result


@sources_router.post("/estimate")
def estimate(
    payload: SourceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sources:read")),
):
    size = dir_size(payload.path, limit_seconds=5.0)
    return {"path": payload.path, "estimated_size": size}
