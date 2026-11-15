"""Dashboard aggregates and server monitoring endpoints."""
from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    ActivityLog,
    BackupHistory,
    BackupJob,
    BackupStatus,
    Notification,
    User,
)
from app.services import monitoring
from app.services.scheduler import status as scheduler_status
from app.utils import utcnow

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("dashboard:read")),
):
    now = utcnow()
    day_ago = now - timedelta(days=1)

    total_jobs = db.scalar(select(func.count(BackupJob.id))) or 0
    enabled_jobs = db.scalar(select(func.count(BackupJob.id)).where(BackupJob.enabled.is_(True))) or 0

    def count_status(status: str) -> int:
        return db.scalar(
            select(func.count(BackupHistory.id)).where(BackupHistory.status == status)
        ) or 0

    success = count_status(BackupStatus.SUCCESS.value)
    failed = count_status(BackupStatus.FAILED.value)
    running = count_status(BackupStatus.RUNNING.value)
    pending = count_status(BackupStatus.PENDING.value)
    total_backups = db.scalar(select(func.count(BackupHistory.id))) or 0

    total_size = db.scalar(
        select(func.coalesce(func.sum(BackupHistory.archive_size), 0)).where(
            BackupHistory.status == BackupStatus.SUCCESS.value
        )
    ) or 0

    last_backup = db.scalar(
        select(BackupHistory)
        .where(BackupHistory.status == BackupStatus.SUCCESS.value)
        .order_by(BackupHistory.finished_at.desc())
        .limit(1)
    )
    next_backup = db.scalar(
        select(BackupJob)
        .where(BackupJob.enabled.is_(True), BackupJob.next_run_at.is_not(None))
        .order_by(BackupJob.next_run_at.asc())
        .limit(1)
    )

    finished = success + failed
    success_rate = round(success / finished * 100, 1) if finished else 0.0

    disk = monitoring.disk_health()
    metrics = monitoring.get_system_metrics()

    # 14-day activity series
    activity = []
    for offset in range(13, -1, -1):
        day_start = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        ok = db.scalar(
            select(func.count(BackupHistory.id)).where(
                BackupHistory.status == BackupStatus.SUCCESS.value,
                BackupHistory.created_at >= day_start,
                BackupHistory.created_at < day_end,
            )
        ) or 0
        bad = db.scalar(
            select(func.count(BackupHistory.id)).where(
                BackupHistory.status == BackupStatus.FAILED.value,
                BackupHistory.created_at >= day_start,
                BackupHistory.created_at < day_end,
            )
        ) or 0
        size = db.scalar(
            select(func.coalesce(func.sum(BackupHistory.archive_size), 0)).where(
                BackupHistory.status == BackupStatus.SUCCESS.value,
                BackupHistory.created_at >= day_start,
                BackupHistory.created_at < day_end,
            )
        ) or 0
        activity.append({"date": day_start.strftime("%Y-%m-%d"), "success": ok, "failed": bad, "size": size})

    recent = db.scalars(
        select(BackupHistory).order_by(BackupHistory.created_at.desc()).limit(8)
    ).all()
    unread = db.scalar(
        select(func.count(Notification.id)).where(Notification.read.is_(False))
    ) or 0
    last_24h = db.scalar(
        select(func.count(BackupHistory.id)).where(BackupHistory.created_at >= day_ago)
    ) or 0

    return {
        "stats": {
            "total_jobs": total_jobs,
            "enabled_jobs": enabled_jobs,
            "successful_backups": success,
            "failed_backups": failed,
            "running_backups": running,
            "pending_backups": pending,
            "total_backups": total_backups,
            "total_backup_size": int(total_size),
            "backup_success_rate": success_rate,
            "backups_last_24h": last_24h,
            "unread_notifications": unread,
        },
        "last_backup": {
            "id": last_backup.id,
            "job_name": last_backup.job_name,
            "finished_at": last_backup.finished_at.isoformat() if last_backup and last_backup.finished_at else None,
            "archive_size": last_backup.archive_size if last_backup else 0,
        } if last_backup else None,
        "next_backup": {
            "job_id": next_backup.id,
            "job_name": next_backup.name,
            "next_run_at": next_backup.next_run_at.isoformat() if next_backup.next_run_at else None,
        } if next_backup else None,
        "disk": disk,
        "system": {
            "cpu_percent": metrics["cpu"]["percent"],
            "memory_percent": metrics["memory"]["percent"],
            "memory_used": metrics["memory"]["used"],
            "memory_total": metrics["memory"]["total"],
            "uptime_seconds": metrics["uptime_seconds"],
            "hostname": metrics["hostname"],
        },
        "activity_series": activity,
        "recent_backups": [
            {
                "id": r.id,
                "job_name": r.job_name,
                "status": r.status,
                "archive_size": r.archive_size,
                "duration_seconds": r.duration_seconds,
                "created_at": r.created_at.isoformat(),
            }
            for r in recent
        ],
        "scheduler": scheduler_status(),
    }


@router.get("/monitoring")
def monitoring_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("monitoring:read")),
):
    metrics = monitoring.get_system_metrics()
    metrics["disk_health"] = monitoring.disk_health()
    metrics["scheduler"] = scheduler_status()
    metrics["backup_service"] = {
        "status": "running",
        "backup_dir": settings.backup_dir,
        "backup_dir_exists": os.path.isdir(settings.backup_dir),
        "max_concurrent": settings.max_concurrent_backups,
    }
    return metrics
