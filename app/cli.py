"""Tokser Backup Manager - command line administration.

Usage from an installed system:

    sudo tbm status
    sudo tbm user passwd admin
    sudo tbm service restart
    sudo tbm job run 3

The CLI shares the application's configuration, database and services, so
anything changed here is immediately visible in the web panel. It never
starts a second scheduler or touches files with the wrong owner: the wrapper
script drops to the service user for database work and stays root only for
`service` commands.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import APP_NAME, APP_SHORT, APP_VERSION, VENDOR, settings

SERVICE_NAME = "TBM"

# Unicode box characters and check marks are used throughout; a console with a
# legacy code page (Windows cp1252, C/POSIX locales) would raise on the first
# print. Fall back to ASCII when the stream cannot encode them.
_UNICODE_OK = True


def _init_encoding() -> None:
    global _UNICODE_OK
    try:
        "─✓✗·→".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        _UNICODE_OK = False
        try:
            sys.stdout.reconfigure(errors="replace")
            sys.stderr.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _u(unicode_text: str, ascii_text: str) -> str:
    return unicode_text if _UNICODE_OK else ascii_text


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


class Out:
    def __init__(self, as_json: bool = False):
        self.json = as_json
        self.color = _use_color()

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def bold(self, t: str) -> str:
        return self._c("1", t)

    def ok(self, t: str) -> str:
        return self._c("32", t)

    def warn(self, t: str) -> str:
        return self._c("33", t)

    def err(self, t: str) -> str:
        return self._c("31", t)

    def dim(self, t: str) -> str:
        return self._c("2", t)

    def emit(self, payload) -> None:
        print(json.dumps(payload, indent=2, default=str))

    def header(self, title: str) -> None:
        if not self.json:
            print()
            print(self.bold(title))
            print(self.dim(_u("─", "-") * max(20, len(title) + 4)))


def _fmt_bytes(n: int | float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def _fmt_time(dt) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _ago(dt) -> str:
    if not dt:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - dt).total_seconds()
    if delta < 0:
        return "in the future"
    for limit, div, unit in ((60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h"), (2592000, 86400, "d")):
        if delta < limit:
            return f"{int(delta / div)}{unit} ago"
    return f"{int(delta / 2592000)}mo ago"


def _is_locked(user) -> bool:
    """True when the account is inside a failed-login lockout window.

    SQLite returns naive datetimes, so the stored value is normalised to UTC
    before comparison; comparing a naive value to an aware one raises.
    """
    locked_until = getattr(user, "locked_until", None)
    if not locked_until:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > datetime.now(timezone.utc)


def _table(rows: list[list[str]], headers: list[str]) -> str:
    """Plain aligned table; no dependency on a formatting library."""
    if not rows:
        return "  (none)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = ["  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("  " + "  ".join(_u("─", "-") * widths[i] for i in range(len(headers))))
    for row in rows:
        out.append("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(out)


_SCHEMA_READY = False


def _db():
    """Open a session, making sure the schema exists.

    An installed system already has the tables, but running the CLI against a
    fresh data directory should create them rather than crash with "no such
    table".
    """
    global _SCHEMA_READY
    if not _SCHEMA_READY:
        from app.core.database import init_db

        init_db()
        _SCHEMA_READY = True
    from app.core.database import SessionLocal

    return SessionLocal()


def _die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
def cmd_status(args, out: Out) -> None:
    from app.models import BackupHistory, BackupJob, User
    from app.services import monitoring

    service_active = _service_is_active()
    db = _db()
    try:
        jobs_total = db.scalar(select(func.count(BackupJob.id))) or 0
        jobs_enabled = db.scalar(
            select(func.count(BackupJob.id)).where(BackupJob.enabled.is_(True))
        ) or 0
        backups = db.scalar(select(func.count(BackupHistory.id))) or 0
        failed = db.scalar(
            select(func.count(BackupHistory.id)).where(BackupHistory.status == "failed")
        ) or 0
        running = db.scalar(
            select(func.count(BackupHistory.id)).where(BackupHistory.status == "running")
        ) or 0
        total_size = db.scalar(
            select(func.coalesce(func.sum(BackupHistory.archive_size), 0)).where(
                BackupHistory.status == "success"
            )
        ) or 0
        users = db.scalar(select(func.count(User.id))) or 0
        next_job = db.scalar(
            select(BackupJob)
            .where(BackupJob.enabled.is_(True), BackupJob.next_run_at.is_not(None))
            .order_by(BackupJob.next_run_at.asc())
            .limit(1)
        )
    finally:
        db.close()

    disk = monitoring.disk_health()

    if out.json:
        out.emit({
            "version": APP_VERSION,
            "service": "active" if service_active else "inactive",
            "database": settings.database_url.split("://")[0],
            "jobs": {"total": jobs_total, "enabled": jobs_enabled},
            "backups": {"total": backups, "failed": failed, "running": running,
                        "total_size": int(total_size)},
            "users": users,
            "disk": disk,
            "next_run": next_job.next_run_at if next_job else None,
        })
        return

    status_txt = out.ok("active") if service_active else out.err("inactive")
    out.header(f"{APP_NAME} {APP_VERSION}")
    print(f"  Service      {status_txt}  ({SERVICE_NAME})")
    print(f"  Vendor       {VENDOR}")
    print(f"  Database     {settings.database_url.split('://')[0]}")
    print(f"  Data dir     {settings.data_dir}")
    print(f"  Backup dir   {settings.backup_dir}")
    print()
    print(f"  Jobs         {jobs_total} total, {jobs_enabled} enabled")
    print(f"  Backups      {backups} total, {failed} failed, {running} running")
    print(f"  Stored       {_fmt_bytes(total_size)}")
    print(f"  Users        {users}")
    if next_job:
        print(f"  Next run     {next_job.name} at {_fmt_time(next_job.next_run_at)}")
    print()
    level_color = out.ok if disk["level"] == "ok" else (out.warn if disk["level"] == "warning" else out.err)
    used_pct = level_color(f"{disk['percent']}% used")
    print(f"  Disk         {used_pct}  {_u('·', '|')}  "
          f"{_fmt_bytes(disk['free'])} free of {_fmt_bytes(disk['total'])}")
    print()


def _service_is_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE_NAME],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        # Not a systemd host (containers, Windows dev): assume it is up.
        return True


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------
def cmd_service(args, out: Out) -> None:
    action = args.action
    if action == "logs":
        cmd = ["journalctl", "-u", SERVICE_NAME, "-n", str(args.lines), "--no-pager"]
        if args.follow:
            cmd.append("-f")
        os.execvp("journalctl", cmd)  # replaces this process, Ctrl-C works
        return

    allowed = {"status", "start", "stop", "restart", "reload", "enable", "disable"}
    if action not in allowed:
        _die(f"unknown service action '{action}'")

    try:
        if action == "status":
            subprocess.run(["systemctl", "status", SERVICE_NAME, "--no-pager",
                            "-n", str(args.lines)], check=False)
            raise SystemExit(0 if _service_is_active() else 3)

        result = subprocess.run(["systemctl", action, SERVICE_NAME],
                                capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        _die("systemctl not found - this is not a systemd host")
    except subprocess.CalledProcessError as exc:
        _die(f"systemctl {action} failed: {exc}")

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if "Access denied" in detail or "authentication" in detail.lower():
            _die(f"permission denied - run with sudo")
        _die(f"systemctl {action} failed: {detail}")

    if action in {"start", "stop", "restart", "reload"}:
        if _service_is_active() == (action != "stop"):
            print(out.ok(f"service {action}ed" if action != "stop" else "service stopped"))
        else:
            _die(f"service did not reach the expected state after '{action}'")
    else:
        print(out.ok(f"service {action}d"))


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------
def _prompt_password(out: Out, confirm: bool = True) -> str:
    if not sys.stdin.isatty():
        _die("no terminal available - pass --password for non-interactive use")
    while True:
        pw = getpass.getpass("  New password: ")
        if len(pw) < 10:
            print(out.err("  too short - at least 10 characters"), file=sys.stderr)
            continue
        if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
            print(out.err("  must contain letters and digits"), file=sys.stderr)
            continue
        if confirm:
            again = getpass.getpass("  Confirm password: ")
            if pw != again:
                print(out.err("  passwords do not match"), file=sys.stderr)
                continue
        return pw


def cmd_user(args, out: Out) -> None:
    from app.core.security import hash_password
    from app.models import Role, SessionToken, User
    from app.services.auth import ensure_roles

    action = args.action
    db = _db()
    try:
        ensure_roles(db)

        if action == "list":
            users = db.scalars(select(User).order_by(User.username)).all()
            if out.json:
                out.emit([{
                    "id": u.id, "username": u.username, "role": u.role_name,
                    "active": u.is_active, "last_login": u.last_login_at,
                    "locked": _is_locked(u),
                } for u in users])
                return
            rows = [[
                u.username,
                u.role_name,
                "yes" if u.is_active else "no",
                _ago(u.last_login_at),
                "LOCKED" if _is_locked(u) else "",
            ] for u in users]
            out.header("Users")
            print(_table(rows, ["USERNAME", "ROLE", "ACTIVE", "LAST LOGIN", ""]))
            print()
            return

        user = db.scalar(select(User).where(func.lower(User.username) == args.username.lower())) \
            if getattr(args, "username", None) else None

        if action == "create":
            if user:
                _die(f"user '{args.username}' already exists", 2)
            if not args.password:
                print(f"  Creating '{args.username}' with role {args.role}")
                args.password = _prompt_password(out)
            role = db.scalar(select(Role).where(Role.name == args.role))
            if role is None:
                _die(f"unknown role '{args.role}'")
            user = User(
                username=args.username.strip(),
                email=args.email or "",
                full_name=args.full_name or "",
                password_hash=hash_password(args.password),
                role_id=role.id,
                is_active=True,
                must_change_password=bool(getattr(args, "force_change", False)),
            )
            db.add(user)
            db.commit()
            print(out.ok(f"created user '{user.username}' ({args.role})"))
            return

        if user is None:
            _die(f"user '{args.username}' not found", 2)

        if action == "passwd":
            pw = args.password or _prompt_password(out)
            user.password_hash = hash_password(pw)
            user.must_change_password = bool(getattr(args, "force_change", False))
            user.failed_attempts = 0
            user.locked_until = None
            # Revoke every session so a compromised session cannot survive.
            revoked = 0
            for s in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id)).all():
                db.delete(s)
                revoked += 1
            db.commit()
            print(out.ok(f"password changed for '{user.username}'"))
            if revoked:
                print(out.dim(f"  {revoked} session(s) revoked"))
            return

        if action == "unlock":
            user.failed_attempts = 0
            user.locked_until = None
            db.commit()
            print(out.ok(f"unlocked '{user.username}'"))
            return

        if action == "role":
            role = db.scalar(select(Role).where(Role.name == args.role))
            if role is None:
                _die(f"unknown role '{args.role}'")
            admins = db.scalar(
                select(func.count(User.id)).join(Role).where(
                    Role.name == "admin", User.is_active.is_(True)
                )
            ) or 0
            if user.role_name == "admin" and args.role != "admin" and admins <= 1:
                _die("refusing to demote the last administrator")
            user.role_id = role.id
            db.commit()
            print(out.ok(f"'{user.username}' is now {args.role}"))
            return

        if action in {"enable", "disable"}:
            admins = db.scalar(
                select(func.count(User.id)).join(Role).where(
                    Role.name == "admin", User.is_active.is_(True)
                )
            ) or 0
            if action == "disable" and user.role_name == "admin" and admins <= 1:
                _die("refusing to disable the last administrator")
            user.is_active = action == "enable"
            if not user.is_active:
                for s in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id)).all():
                    db.delete(s)
            db.commit()
            print(out.ok(f"user '{user.username}' {action}d"))
            return

        if action == "delete":
            admins = db.scalar(
                select(func.count(User.id)).join(Role).where(
                    Role.name == "admin", User.is_active.is_(True)
                )
            ) or 0
            if user.role_name == "admin" and admins <= 1:
                _die("refusing to delete the last administrator")
            if not args.yes:
                _die("refusing to delete without --yes")
            name = user.username
            db.delete(user)
            db.commit()
            print(out.ok(f"deleted user '{name}'"))
            return

        _die(f"unknown user action '{action}'")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# job
# ---------------------------------------------------------------------------
def cmd_job(args, out: Out) -> None:
    from app.models import BackupJob
    from app.services.cron import describe_schedule
    from app.services.scheduler import recalculate_job_next_run

    db = _db()
    try:
        if args.action == "list":
            jobs = db.scalars(select(BackupJob).order_by(BackupJob.name)).all()
            if out.json:
                out.emit([{
                    "id": j.id, "name": j.name, "enabled": j.enabled,
                    "last_status": j.last_status, "last_run": j.last_run_at,
                    "next_run": j.next_run_at, "runs": j.total_runs,
                    "success": j.success_runs, "failed": j.failed_runs,
                } for j in jobs])
                return
            rows = [[
                j.id, j.name,
                "on" if j.enabled else "off",
                j.last_status or "-",
                _ago(j.last_run_at),
                _fmt_time(j.next_run_at) if j.next_run_at else "-",
            ] for j in jobs]
            out.header("Backup jobs")
            print(_table(rows, ["ID", "NAME", "ENABLED", "LAST", "LAST RUN", "NEXT RUN"]))
            print()
            return

        job = db.get(BackupJob, args.job_id)
        if job is None:
            _die(f"job {args.job_id} not found", 2)

        if args.action == "show":
            if out.json:
                out.emit({
                    "id": job.id, "name": job.name, "enabled": job.enabled,
                    "compression": job.compression, "level": job.compression_level,
                    "sources": [{"path": s.path, "enabled": s.enabled} for s in job.sources],
                    "schedule": describe_schedule(
                        job.schedule.schedule_type,
                        interval_value=job.schedule.interval_value,
                        hour=job.schedule.hour, minute=job.schedule.minute,
                        day_of_week=job.schedule.day_of_week,
                        day_of_month=job.schedule.day_of_month,
                        cron_expression=job.schedule.cron_expression,
                    ) if job.schedule else "manual",
                    "next_run": job.next_run_at,
                    "last_error": job.last_error,
                })
                return
            out.header(f"Job {job.id}: {job.name}")
            print(f"  Enabled      {'yes' if job.enabled else 'no'}")
            print(f"  Compression  {job.compression} (level {job.compression_level})")
            sched = "manual"
            if job.schedule:
                sched = describe_schedule(
                    job.schedule.schedule_type,
                    interval_value=job.schedule.interval_value,
                    hour=job.schedule.hour, minute=job.schedule.minute,
                    day_of_week=job.schedule.day_of_week,
                    day_of_month=job.schedule.day_of_month,
                    cron_expression=job.schedule.cron_expression,
                )
            print(f"  Schedule     {sched}  ({job.schedule.timezone if job.schedule else '-'})")
            print(f"  Next run     {_fmt_time(job.next_run_at)}")
            print(f"  Runs         {job.total_runs} ({job.success_runs} ok, {job.failed_runs} failed)")
            print(f"  Sources      {len(job.sources)}")
            for s in job.sources:
                mark = _u("✓", "+") if s.enabled else _u("×", "-")
                print(f"    {mark} {s.path}")
            if job.last_error:
                print(f"  Last error   {out.err(job.last_error[:300])}")
            print()
            return

        if args.action == "run":
            from app.services.backup_engine import BackupError, start_job

            try:
                backup_id = start_job(job.id, trigger="cli")
            except BackupError as exc:
                _die(str(exc))
            print(out.ok(f"started job '{job.name}' (backup #{backup_id})"))
            if args.wait:
                import time
                from app.models import BackupHistory

                print(out.dim("waiting for completion..."))
                for _ in range(3600):
                    db.expire_all()
                    b = db.get(BackupHistory, backup_id)
                    if b and b.status not in ("pending", "running"):
                        if b.status == "success":
                            print(out.ok(f"completed: {b.archive_name} "
                                         f"({_fmt_bytes(b.archive_size)}) in {b.duration_seconds:.0f}s"))
                        else:
                            print(out.err(f"{b.status}: {b.error_message[:300]}"))
                            raise SystemExit(1)
                        return
                    time.sleep(1)
                _die("timed out waiting for the backup")
            return

        if args.action in {"enable", "disable"}:
            job.enabled = args.action == "enable"
            db.commit()
            recalculate_job_next_run(job.id)
            print(out.ok(f"job '{job.name}' {args.action}d"))
            return

        _die(f"unknown job action '{args.action}'")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------
def cmd_backup(args, out: Out) -> None:
    from app.models import BackupHistory
    from app.services import archive as archive_svc
    from app.core.security import decrypt_secret
    from app.models import BackupJob

    db = _db()
    try:
        if args.action == "list":
            stmt = select(BackupHistory).order_by(BackupHistory.created_at.desc())
            if args.job_id:
                stmt = stmt.where(BackupHistory.job_id == args.job_id)
            if args.status:
                stmt = stmt.where(BackupHistory.status == args.status)
            rows_db = db.scalars(stmt.limit(args.limit)).all()
            if out.json:
                out.emit([{
                    "id": b.id, "job": b.job_name, "status": b.status,
                    "size": b.archive_size, "created": b.created_at,
                    "archive": b.archive_name,
                } for b in rows_db])
                return
            rows = [[
                b.id, b.job_name, b.status,
                _fmt_bytes(b.archive_size),
                _ago(b.created_at),
            ] for b in rows_db]
            out.header("Backups")
            print(_table(rows, ["ID", "JOB", "STATUS", "SIZE", "WHEN"]))
            print()
            return

        backup = db.get(BackupHistory, args.backup_id)
        if backup is None:
            _die(f"backup {args.backup_id} not found", 2)

        if args.action == "show":
            info = {
                "id": backup.id, "job": backup.job_name, "status": backup.status,
                "archive": backup.archive_name, "size": backup.archive_size,
                "files": backup.file_count, "verified": backup.verified,
                "checksum": backup.checksum, "started": backup.started_at,
                "finished": backup.finished_at, "duration": backup.duration_seconds,
                "telegram": backup.telegram_status, "error": backup.error_message,
            }
            if out.json:
                out.emit(info)
                return
            out.header(f"Backup #{backup.id}")
            for key, value in info.items():
                print(f"  {key:<10} {value if value not in ('', None) else '-'}")
            print()
            return

        if args.action == "verify":
            if not backup.archive_path or not os.path.isfile(backup.archive_path):
                _die("archive file is missing from disk")
            job = db.get(BackupJob, backup.job_id) if backup.job_id else None
            # Derive the format from the archive name; fall back to the job's
            # configured compression when the name carries no extension.
            name = (backup.archive_name or "").lower()
            if name.endswith(".enc"):
                name = name[:-4]
            fmt = next(
                (c for c in ("tar.gz", "tar", "zip", "zst") if name.endswith("." + c)),
                job.compression if job else "tar.gz",
            )
            password = decrypt_secret(job.encryption_password_enc) if job and job.encrypt_archive else ""
            ok_, msg = archive_svc.verify_archive(backup.archive_path, fmt, password)
            backup.verified = ok_
            db.commit()
            print(out.ok(f"archive verified ({msg})") if ok_ else out.err(f"verification failed: {msg}"))
            raise SystemExit(0 if ok_ else 1)

        if args.action == "delete":
            if backup.status == "running":
                _die("cannot delete a running backup")
            if not args.yes:
                _die("refusing to delete without --yes")
            freed = 0
            if backup.archive_path and os.path.isfile(backup.archive_path):
                freed = os.path.getsize(backup.archive_path)
                os.unlink(backup.archive_path)
            db.delete(backup)
            db.commit()
            print(out.ok(f"deleted backup #{args.backup_id}, freed {_fmt_bytes(freed)}"))
            return

        _die(f"unknown backup action '{args.action}'")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# maintenance
# ---------------------------------------------------------------------------
def cmd_maintenance(args, out: Out) -> None:
    if args.action == "recalc":
        from app.services.scheduler import recalculate_all

        count = recalculate_all()
        print(out.ok(f"recomputed next run times for {count} job(s)"))
        return

    if args.action == "prune-sessions":
        from app.services.auth import purge_expired_sessions

        db = _db()
        try:
            removed = purge_expired_sessions(db)
        finally:
            db.close()
        print(out.ok(f"removed {removed} expired session(s)"))
        return

    if args.action == "prune-login-attempts":
        from datetime import timedelta

        from app.models import LoginAttempt

        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        db = _db()
        try:
            rows = db.scalars(select(LoginAttempt).where(LoginAttempt.created_at < cutoff)).all()
            for row in rows:
                db.delete(row)
            db.commit()
            print(out.ok(f"removed {len(rows)} login attempt(s) older than {args.days} days"))
        finally:
            db.close()
        return

    if args.action == "vacuum":
        if not settings.is_sqlite:
            _die("vacuum is only meaningful for SQLite")
        from app.core.database import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
        print(out.ok("database vacuumed"))
        return

    if args.action == "check-disk":
        from app.services import monitoring

        health = monitoring.disk_health()
        msg = (f"{health['path']}: {health['percent']}% used, "
               f"{_fmt_bytes(health['free'])} free - {health['level']}")
        print(out.ok(msg) if health["level"] == "ok" else out.warn(msg))
        raise SystemExit(0 if health["level"] == "ok" else 1)

    _die(f"unknown maintenance action '{args.action}'")


# ---------------------------------------------------------------------------
# access - grant the service account read access to protected paths
# ---------------------------------------------------------------------------
APP_USER = "TBM"


def _setfacl_available() -> bool:
    import shutil as sh

    return sh.which("setfacl") is not None


def cmd_access(args, out: Out) -> None:
    """Grant or revoke read access for the service account.

    The application runs as an unprivileged user, so it cannot read /root or
    other 0700 trees. Rather than running the service as root (which would give
    any web vulnerability full system access), a POSIX ACL grants this single
    account read + traverse permission on the specific path.
    """
    import subprocess

    action = args.action
    path = os.path.abspath(os.path.expanduser(args.path)) if getattr(args, "path", None) else ""

    if not hasattr(os, "geteuid"):
        _die("access management requires Linux")
    if os.geteuid() != 0:
        _die("access changes need root - run with sudo")

    if action == "check":
        path = path or "/root"
        readable = _can_read_as_service(path)
        listed = _acl_entries(path)
        if out.json:
            out.emit({"path": path, "readable": readable, "acl": listed})
            return
        state = out.ok("readable") if readable else out.err("NOT readable")
        print(f"  {path}: {state}")
        if listed:
            print(out.dim(f"  ACL: {', '.join(listed)}"))
        elif not readable:
            print(out.dim(f"  grant with:  sudo tbm access grant {path}"))
        raise SystemExit(0 if readable else 1)

    if action == "list":
        for target in args.paths or ["/root", "/home"]:
            target = os.path.abspath(os.path.expanduser(target))
            entries = _acl_entries(target)
            print(f"  {target}: {', '.join(entries) if entries else out.dim('no ACL')}")
        return

    if not path:
        _die("a path is required")
    if not os.path.exists(path):
        _die(f"path does not exist: {path}")
    if not _setfacl_available():
        _die("setfacl not found — install it with: sudo apt-get install acl")

    if action == "grant":
        # "rX" grants read on files and traverse on directories; it never
        # grants write, so backups cannot alter the source.
        results = []
        for target in [path] + _subdirs_needing_traverse(path):
            r = subprocess.run(["setfacl", "-m", f"u:{APP_USER}:rX", target],
                               capture_output=True, text=True)
            results.append((target, r.returncode, (r.stderr or "").strip()))
        failed = [r for r in results if r[1] != 0]
        if failed:
            for target, _, msg in failed:
                print(out.err(f"  failed {target}: {msg}"), file=sys.stderr)
            _die("some ACLs could not be applied")
        readable = _can_read_as_service(path)
        print(out.ok(f"granted read access on {path} to '{APP_USER}'")
              if readable else out.warn(
                  f"ACL applied on {path} but '{APP_USER}' still cannot read it — "
                  "check SELinux/AppArmor"))
        if path in ("/root", "/home") or path.startswith(("/root/", "/home/")):
            print(out.dim("  restart the service so the new access is picked up: "
                          "tbm service restart"))
        raise SystemExit(0 if readable else 1)

    if action == "revoke":
        r = subprocess.run(["setfacl", "-x", f"u:{APP_USER}", path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            _die(f"could not revoke: {(r.stderr or '').strip()}")
        print(out.ok(f"revoked access on {path} for '{APP_USER}'"))
        return

    _die(f"unknown access action '{action}'")


def _subdirs_needing_traverse(path: str) -> list[str]:
    """Parents of a deep path need +x for the account to reach it."""
    parents = []
    parent = os.path.dirname(path)
    while parent and parent != "/":
        parents.append(parent)
        parent = os.path.dirname(parent)
    return parents


def _acl_entries(path: str) -> list[str]:
    import subprocess

    try:
        r = subprocess.run(["getfacl", "-p", "-c", path], capture_output=True,
                           text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.startswith("user:")]


def _can_read_as_service(path: str) -> bool:
    """Actually test access as the service account, not as root."""
    import subprocess

    try:
        r = subprocess.run(
            ["runuser", "-u", APP_USER, "--", "test", "-r", path],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            # Traverse the whole path, not just the leaf.
            for sub in _subdirs_needing_traverse(path):
                if sub in ("/root", "/home"):
                    continue
                r2 = subprocess.run(["runuser", "-u", APP_USER, "--", "test", "-x", sub],
                                    capture_output=True, timeout=10)
                if r2.returncode != 0:
                    return False
            return True
        return False
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# doctor / version
# ---------------------------------------------------------------------------
def cmd_doctor(args, out: Out) -> None:
    """Check the things that commonly break after a deployment change."""
    problems = 0
    out.header("Environment check")

    def check(label: str, ok_: bool, detail: str = "") -> None:
        nonlocal problems
        mark = out.ok(_u("✓", "OK")) if ok_ else out.err(_u("✗", "X"))
        print(f"  {mark} {label}" + (f"  {out.dim(detail)}" if detail else ""))
        if not ok_:
            problems += 1

    check("Python 3.12+", sys.version_info >= (3, 12), sys.version.split()[0])
    check("Config loaded", bool(settings.database_url), settings.database_url.split("://")[0])
    check("Data directory writable", os.access(settings.data_dir, os.W_OK), settings.data_dir)
    check("Backup directory writable", os.access(settings.backup_dir, os.W_OK), settings.backup_dir)
    check("Encryption key present", bool(settings.encryption_key))
    check("Secret key present", bool(settings.secret_key))

    try:
        from sqlalchemy import text

        from app.core.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        check("Database reachable", True)
    except Exception as exc:
        check("Database reachable", False, str(exc)[:120])

    free = 0
    try:
        import shutil

        free = shutil.disk_usage(settings.backup_dir).free
    except OSError:
        pass
    check("Free disk space", free >= settings.min_free_disk_mb * 1024 * 1024,
          f"{_fmt_bytes(free)} free")

    for tool, label in (("tar", "tar"), ("mysqldump", "mysqldump (optional)"),
                        ("pg_dump", "pg_dump (optional)")):
        import shutil as sh

        found = sh.which(tool) is not None
        if tool in {"tar"}:
            check(f"{label} available", found)
        elif not found:
            print(f"  {out.warn(_u('·', '-'))} {label} not installed")

    print()
    if problems:
        print(out.err(f"{problems} problem(s) found"))
        raise SystemExit(1)
    print(out.ok("All checks passed"))


def cmd_version(args, out: Out) -> None:
    if out.json:
        out.emit({"name": APP_NAME, "short": APP_SHORT, "version": APP_VERSION, "vendor": VENDOR})
        return
    print(f"{APP_NAME} {APP_VERSION} - {VENDOR}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tbm",
        description=f"{APP_NAME} - command line administration",
        epilog="Run 'tbm <command> --help' for details on a command.",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {APP_VERSION}")

    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("status", help="overall system status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("doctor", help="diagnose configuration and environment problems")
    s.set_defaults(func=cmd_doctor)

    # service
    s = sub.add_parser("service", help="control the systemd service")
    s.add_argument("action", choices=["status", "start", "stop", "restart", "reload",
                                      "enable", "disable", "logs"])
    s.add_argument("-n", "--lines", type=int, default=50, help="log/status lines")
    s.add_argument("-f", "--follow", action="store_true", help="follow logs (with 'logs')")
    s.set_defaults(func=cmd_service)

    # user
    s = sub.add_parser("user", help="manage accounts")
    us = s.add_subparsers(dest="action", metavar="<action>")
    us.add_parser("list", help="list accounts").set_defaults(func=cmd_user)

    u = us.add_parser("create", help="create an account")
    u.add_argument("username")
    u.add_argument("--role", default="viewer", choices=["admin", "operator", "viewer"])
    u.add_argument("--password", help="non-interactive password")
    u.add_argument("--email", default="")
    u.add_argument("--full-name", default="")
    u.add_argument("--force-change", action="store_true", help="require a change at first login")
    u.set_defaults(func=cmd_user)

    u = us.add_parser("passwd", help="change a password (also clears lockout)")
    u.add_argument("username")
    u.add_argument("--password", help="non-interactive password")
    u.add_argument("--force-change", action="store_true")
    u.set_defaults(func=cmd_user)

    for name, helptext in (("enable", "re-enable an account"),
                           ("disable", "disable an account"),
                           ("unlock", "clear failed-login lockout")):
        u = us.add_parser(name, help=helptext)
        u.add_argument("username")
        u.set_defaults(func=cmd_user)

    u = us.add_parser("role", help="change a role")
    u.add_argument("username")
    u.add_argument("role", choices=["admin", "operator", "viewer"])
    u.set_defaults(func=cmd_user)

    u = us.add_parser("delete", help="delete an account")
    u.add_argument("username")
    u.add_argument("--yes", action="store_true", help="required confirmation")
    u.set_defaults(func=cmd_user)

    # job
    s = sub.add_parser("job", help="manage backup jobs")
    js = s.add_subparsers(dest="action", metavar="<action>")
    js.add_parser("list", help="list jobs").set_defaults(func=cmd_job)
    j = js.add_parser("show", help="show one job")
    j.add_argument("job_id", type=int)
    j.set_defaults(func=cmd_job)
    j = js.add_parser("run", help="run a job now")
    j.add_argument("job_id", type=int)
    j.add_argument("-w", "--wait", action="store_true", help="wait for completion")
    j.set_defaults(func=cmd_job)
    for name in ("enable", "disable"):
        j = js.add_parser(name, help=f"{name} a job")
        j.add_argument("job_id", type=int)
        j.set_defaults(func=cmd_job)

    # backup
    s = sub.add_parser("backup", help="inspect stored backups")
    bs = s.add_subparsers(dest="action", metavar="<action>")
    b = bs.add_parser("list", help="list backups")
    b.add_argument("--limit", type=int, default=20)
    b.add_argument("--job", dest="job_id", type=int)
    b.add_argument("--status", choices=["success", "failed", "running", "pending", "cancelled"])
    b.set_defaults(func=cmd_backup)
    b = bs.add_parser("show", help="show one backup")
    b.add_argument("backup_id", type=int)
    b.set_defaults(func=cmd_backup)
    b = bs.add_parser("verify", help="re-verify an archive")
    b.add_argument("backup_id", type=int)
    b.set_defaults(func=cmd_backup)
    b = bs.add_parser("delete", help="delete a backup and its archive")
    b.add_argument("backup_id", type=int)
    b.add_argument("--yes", action="store_true", help="required confirmation")
    b.set_defaults(func=cmd_backup)

    # maintenance
    s = sub.add_parser("maintenance", help="housekeeping tasks")
    ms = s.add_subparsers(dest="action", metavar="<action>")
    ms.add_parser("recalc", help="recompute all schedule next-run times").set_defaults(func=cmd_maintenance)
    ms.add_parser("prune-sessions", help="delete expired sessions").set_defaults(func=cmd_maintenance)
    ms.add_parser("vacuum", help="compact the SQLite database").set_defaults(func=cmd_maintenance)
    ms.add_parser("check-disk", help="exit non-zero when disk is low").set_defaults(func=cmd_maintenance)
    m = ms.add_parser("prune-login-attempts", help="delete old login attempt rows")
    m.add_argument("--days", type=int, default=30)
    m.set_defaults(func=cmd_maintenance)

    # access
    s = sub.add_parser(
        "access",
        help=f"grant '{APP_USER}' read access to a protected path (e.g. /root)",
    )
    asub = s.add_subparsers(dest="action", metavar="<action>")

    a = asub.add_parser("grant", help="allow the service account to read a path")
    a.add_argument("path")
    a.set_defaults(func=cmd_access)

    a = asub.add_parser("revoke", help="remove that access")
    a.add_argument("path")
    a.set_defaults(func=cmd_access)

    a = asub.add_parser("check", help="report whether the path is readable")
    a.add_argument("path", nargs="?", default="/root")
    a.set_defaults(func=cmd_access)

    a = asub.add_parser("list", help="show ACLs on common protected paths")
    a.add_argument("paths", nargs="*")
    a.set_defaults(func=cmd_access)

    s = sub.add_parser("version", help="print the version")
    s.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    _init_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Out(as_json=getattr(args, "json", False))

    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    if not hasattr(args, "func"):
        parser.parse_args([args.command, "--help"])
        return 0

    from app.core.logging import setup_logging

    # The CLI prints its own output; keep the log file quiet on stdout.
    os.environ.setdefault("TBM_CLI", "1")
    setup_logging()

    try:
        args.func(args, out)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        _die(f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
