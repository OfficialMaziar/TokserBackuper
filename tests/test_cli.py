"""Command line interface tests.

The CLI shares the application database, so these tests exercise the same
paths an administrator uses from a terminal: account management, safety
guards, job control and backup inspection.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Invoke the CLI in-process and capture its output."""
    from app.cli import main

    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            main(list(argv))
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def _ensure_admin(username: str = "cliadmin", password: str = "CliAdminPass123") -> None:
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import Role, User
    from app.core.security import hash_password
    from app.services.auth import ensure_roles

    db = SessionLocal()
    try:
        ensure_roles(db)
        if db.scalar(select(User).where(func.lower(User.username) == username)) is None:
            role = db.scalar(select(Role).where(Role.name == "admin"))
            db.add(User(username=username, password_hash=hash_password(password),
                        role_id=role.id, is_active=True))
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Basic commands
# ---------------------------------------------------------------------------
def test_version():
    code, out, _ = run_cli("version")
    assert code == 0
    assert "Tokser BackUp Manager".lower() in out.lower() or "tokser backup manager" in out.lower()
    assert "1.0.0" in out


def test_status_runs(admin_client):
    code, out, _ = run_cli("status")
    assert code == 0
    assert "Jobs" in out
    assert "Disk" in out


def test_status_json(admin_client):
    import json

    code, out, _ = run_cli("--json", "status")
    assert code == 0
    payload = json.loads(out)
    assert payload["version"] == "1.0.0"
    assert "jobs" in payload and "backups" in payload


def test_doctor_reports_environment(admin_client):
    code, out, _ = run_cli("doctor")
    assert "Python 3.12+" in out
    assert "Database reachable" in out
    # Exit code is 0 when healthy, 1 when something is wrong; both are valid
    # here, but the output must always name the checks.
    assert code in (0, 1)


def test_help_without_command():
    code, out, _ = run_cli()
    assert code == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def test_create_and_list_user(admin_client):
    import uuid

    # Unique per run so the test is order-independent and re-runnable.
    name = f"cli_op_{uuid.uuid4().hex[:8]}"
    code, out, err = run_cli("user", "create", name, "--role", "operator",
                             "--password", "OperatorPass123")
    assert code == 0, f"code={code} out={out!r} err={err!r}"
    assert "created user" in out

    code, out, err = run_cli("user", "list")
    assert code == 0, f"code={code} err={err!r}"
    assert name in out
    assert "operator" in out


def test_duplicate_user_rejected(admin_client):
    run_cli("user", "create", "dup_user", "--password", "DupUserPass123")
    code, _, err = run_cli("user", "create", "dup_user", "--password", "DupUserPass123")
    assert code == 2
    assert "already exists" in err


def test_weak_password_rejected(admin_client):
    code, _, err = run_cli("user", "create", "weak_user", "--password", "short")
    assert code != 0
    assert "password" in err.lower() or "at least" in err.lower()


def test_password_change(admin_client):
    run_cli("user", "create", "pw_user", "--password", "OldPassword123")
    code, out, _ = run_cli("user", "passwd", "pw_user", "--password", "NewPassword456")
    assert code == 0, out

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import verify_password
    from app.models import User

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == "pw_user"))
        assert verify_password("NewPassword456", user.password_hash)
        assert not verify_password("OldPassword123", user.password_hash)
    finally:
        db.close()


def test_password_change_revokes_sessions(admin_client):
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models import Role, SessionToken, User

    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.name == "viewer"))
        user = User(username="session_user", password_hash=hash_password("SessionPass123"),
                    role_id=role.id, is_active=True)
        db.add(user)
        db.commit()
        db.add(SessionToken(user_id=user.id, token_hash="deadbeef", csrf_token="x",
                            expires_at=__import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc)
                            + __import__("datetime").timedelta(days=1)))
        db.commit()
        uid = user.id
    finally:
        db.close()

    code, out, _ = run_cli("user", "passwd", "session_user", "--password", "AnotherPass789")
    assert code == 0
    assert "revoked" in out

    db = SessionLocal()
    try:
        remaining = db.scalar(
            select(func.count(SessionToken.id)).where(SessionToken.user_id == uid)
        )
        assert remaining == 0
    finally:
        db.close()


def test_unlock_clears_lockout(admin_client):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models import Role, User

    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.name == "viewer"))
        user = User(username="locked_user", password_hash=hash_password("LockedPass123"),
                    role_id=role.id, is_active=True, failed_attempts=5,
                    locked_until=datetime.now(timezone.utc) + timedelta(minutes=15))
        db.add(user)
        db.commit()
        uid = user.id
    finally:
        db.close()

    code, out, _ = run_cli("user", "unlock", "locked_user")
    assert code == 0
    assert "unlocked" in out

    db = SessionLocal()
    try:
        user = db.get(User, uid)
        assert user.failed_attempts == 0
        assert user.locked_until is None
    finally:
        db.close()


def test_cannot_demote_last_admin(admin_client):
    """The only administrator must not be demotable from the CLI."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        admins = [u for u in db.scalars(select(User)).all() if u.role_name == "admin" and u.is_active]
        assert len(admins) == 1, "test expects exactly one active administrator"
        target = admins[0].username
    finally:
        db.close()

    code, out, err = run_cli("user", "role", target, "viewer")
    assert code == 1, f"code={code} out={out!r} err={err!r}"
    assert "last administrator" in err


def test_cannot_delete_without_confirmation(admin_client):
    run_cli("user", "create", "deleteme", "--password", "DeleteMePass123")
    code, _, err = run_cli("user", "delete", "deleteme")
    assert code == 1
    assert "--yes" in err


def test_unknown_user(admin_client):
    code, _, err = run_cli("user", "passwd", "nosuchuser", "--password", "WhateverPass123")
    assert code == 2
    assert "not found" in err


# ---------------------------------------------------------------------------
# Jobs and backups
# ---------------------------------------------------------------------------
def test_job_list_and_show(admin_client, sample_tree):
    r = admin_client.post("/api/v1/jobs", json={
        "name": "CLI Job", "compression": "tar.gz",
        "sources": [{"path": str(sample_tree), "enabled": True}],
        "schedule": {"schedule_type": "weekly", "day_of_week": 1, "hour": 4},
    })
    assert r.status_code == 200
    job_id = r.json()["id"]

    code, out, _ = run_cli("job", "list")
    assert code == 0
    assert "CLI Job" in out

    code, out, _ = run_cli("job", "show", str(job_id))
    assert code == 0
    assert "Weekly" in out
    assert str(sample_tree) in out


def test_job_run_and_backup_inspect(admin_client, sample_tree):
    r = admin_client.post("/api/v1/jobs", json={
        "name": "CLI Run Job",
        "sources": [{"path": str(sample_tree), "enabled": True}],
        "schedule": {"schedule_type": "manual"},
    })
    job_id = r.json()["id"]

    code, out, _ = run_cli("job", "run", str(job_id), "--wait")
    assert code == 0, out
    assert "completed" in out

    code, out, _ = run_cli("backup", "list")
    assert code == 0
    assert "CLI Run Job" in out

    import re

    match = re.search(r"^\s+(\d+)\s+CLI Run Job", out, re.MULTILINE)
    assert match, out
    backup_id = match.group(1)

    code, out, _ = run_cli("backup", "verify", backup_id)
    assert code == 0
    assert "verified" in out


def test_job_run_unknown(admin_client):
    code, _, err = run_cli("job", "run", "99999")
    assert code == 2
    assert "not found" in err


def test_backup_delete_requires_confirmation(admin_client, sample_tree):
    r = admin_client.post("/api/v1/jobs", json={
        "name": "Delete Guard Job",
        "sources": [{"path": str(sample_tree), "enabled": True}],
        "schedule": {"schedule_type": "manual"},
    })
    job_id = r.json()["id"]
    run_cli("job", "run", str(job_id), "--wait")

    code, _, err = run_cli("backup", "delete", "1")
    assert code == 1
    assert "--yes" in err


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def test_maintenance_recalc(admin_client, sample_tree):
    admin_client.post("/api/v1/jobs", json={
        "name": "Recalc Job",
        "sources": [{"path": str(sample_tree), "enabled": True}],
        "schedule": {"schedule_type": "daily", "hour": 5},
    })
    code, out, _ = run_cli("maintenance", "recalc")
    assert code == 0
    assert "recomputed" in out


def test_maintenance_prune_sessions(admin_client):
    code, out, _ = run_cli("maintenance", "prune-sessions")
    assert code == 0
    assert "expired session" in out


def test_invalid_command_exits_nonzero():
    code, _, _ = run_cli("notacommand")
    assert code != 0


# ---------------------------------------------------------------------------
# access - ACL management for protected paths
# ---------------------------------------------------------------------------
def test_access_requires_linux_and_root(admin_client):
    """The access command must refuse cleanly rather than crash."""
    import os

    code, out, err = run_cli("access", "grant", "/root")
    if not hasattr(os, "geteuid"):
        assert code == 1
        assert "Linux" in err
    else:
        # On Linux without root the command must refuse, not proceed.
        assert code == 1
        assert "root" in err.lower()


def test_access_check_reports_readable_state(admin_client):
    """`access check` exits 0/1 and always prints a state line."""
    import os
    import tempfile

    if not hasattr(os, "geteuid"):
        code, _, err = run_cli("access", "check", "/root")
        assert code == 1
        return

    target = tempfile.mkdtemp()
    code, out, err = run_cli("access", "check", target)
    assert code in (0, 1)
    if code == 0:
        assert "readable" in out


def test_access_help_lists_actions(admin_client):
    code, out, _ = run_cli("access", "--help")
    assert code == 0
    for action in ("grant", "revoke", "check", "list"):
        assert action in out


def test_service_user_constant_is_not_root():
    """A guard against someone 'fixing' access by running the service as root."""
    from app.cli import APP_USER

    assert APP_USER not in {"root", "0", "sudo"}
    assert APP_USER == "TBM"
