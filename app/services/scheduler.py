"""Built-in scheduler.

A single background thread wakes every ``scheduler_tick_seconds``, finds jobs
whose ``next_run_at`` has passed and starts them. Overlap is prevented by the
backup engine (a running job cannot be started twice). After each run the next
execution time is recomputed and persisted, so schedules survive restarts.

This replaces APScheduler with a small, dependency-free implementation that
gives us exact control over persistence and timezone handling.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import get_logger
from app.models import ActivityLog, BackupJob, JobStatus, Schedule
from app.services.cron import compute_next_run
from app.utils import ensure_utc, utcnow

log = get_logger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()
_last_tick: datetime | None = None
_started_at: datetime | None = None


def _schedule_kwargs(schedule: Schedule) -> dict:
    return {
        "interval_value": schedule.interval_value,
        "hour": schedule.hour,
        "minute": schedule.minute,
        "day_of_week": schedule.day_of_week,
        "day_of_month": schedule.day_of_month,
        "cron_expression": schedule.cron_expression,
        "timezone_name": schedule.timezone,
        "start_date": ensure_utc(schedule.start_date),
        "end_date": ensure_utc(schedule.end_date),
        "paused": schedule.paused,
    }


def compute_job_next_run(job: BackupJob, now: datetime | None = None) -> datetime | None:
    if not job.enabled or job.schedule is None:
        return None
    sched = job.schedule
    return compute_next_run(sched.schedule_type, **_schedule_kwargs(sched), now=now)


def recalculate_job_next_run(job_id: int) -> None:
    with session_scope() as db:
        job = db.get(BackupJob, job_id)
        if job is None:
            return
        job.next_run_at = compute_job_next_run(job)
        if job.schedule:
            job.schedule.last_calculated_at = utcnow()


def recalculate_all() -> int:
    count = 0
    with session_scope() as db:
        jobs = db.scalars(select(BackupJob)).all()
        for job in jobs:
            job.next_run_at = compute_job_next_run(job)
            count += 1
    return count


def _tick() -> None:
    global _last_tick
    now = utcnow()
    _last_tick = now
    due_jobs: list[int] = []
    with session_scope() as db:
        jobs = db.scalars(
            select(BackupJob).where(
                BackupJob.enabled.is_(True),
                BackupJob.next_run_at.is_not(None),
            )
        ).all()
        for job in jobs:
            next_run = ensure_utc(job.next_run_at)
            if next_run is None or next_run > now:
                continue
            if job.schedule and job.schedule.paused:
                job.next_run_at = compute_job_next_run(job, now=now)
                continue
            due_jobs.append(job.id)

    for job_id in due_jobs:
        # Advance the schedule *before* starting the run. Otherwise a backup
        # that takes longer than one tick would be seen as due again on the
        # next pass and produce a stream of "already running" skips.
        _advance_schedule(job_id)
        _trigger(job_id)


def _trigger(job_id: int) -> None:
    from app.services.backup_engine import BackupError, start_job, is_job_active

    try:
        if is_job_active(job_id):
            log.info("Scheduled job %s skipped: previous run still active", job_id)
            _advance_schedule(job_id)
            return
        start_job(job_id, trigger="schedule")
        log.info("Scheduled job %s started", job_id)
    except BackupError as exc:
        log.warning("Scheduled job %s could not start: %s", job_id, exc)
        _reschedule_after_skip(job_id)
        with session_scope() as db:
            job = db.get(BackupJob, job_id)
            if job:
                job.last_error = f"Scheduler: {exc}"
            db.add(
                ActivityLog(
                    username="scheduler",
                    action="scheduler.error",
                    entity_type="job",
                    entity_id=str(job_id),
                    detail=str(exc),
                    level="warning",
                )
            )
    except Exception as exc:  # pragma: no cover
        log.exception("Scheduler error for job %s", job_id)
        _reschedule_after_skip(job_id)


def _advance_schedule(job_id: int) -> None:
    """Recompute and persist the job's next run time.

    Called when a job is triggered (so a long run cannot be re-triggered on a
    later tick) and when a trigger is refused or skipped.
    """
    try:
        recalculate_job_next_run(job_id)
    except Exception:
        log.debug("Reschedule failed", exc_info=True)


def _loop() -> None:
    log.info("Scheduler thread started (tick=%ss)", settings.scheduler_tick_seconds)
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            log.exception("Scheduler tick failed")
        _stop.wait(max(5, settings.scheduler_tick_seconds))
    log.info("Scheduler thread stopped")


def start_scheduler() -> None:
    global _thread, _started_at
    with _lock:
        if _thread and _thread.is_alive():
            return
        if not settings.scheduler_enabled:
            log.info("Scheduler disabled by configuration")
            return
        _stop.clear()
        _started_at = utcnow()
        recalculate_all()
        _thread = threading.Thread(target=_loop, name="tbm-scheduler", daemon=True)
        _thread.start()


def stop_scheduler(timeout: float = 5.0) -> None:
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=timeout)
        _thread = None


def status() -> dict:
    return {
        "enabled": settings.scheduler_enabled,
        "running": bool(_thread and _thread.is_alive()),
        "started_at": _started_at.isoformat() if _started_at else None,
        "last_tick": _last_tick.isoformat() if _last_tick else None,
        "tick_seconds": settings.scheduler_tick_seconds,
    }
