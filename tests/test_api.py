"""API integration tests: auth, RBAC, CSRF, jobs, backups, restore, settings."""
from __future__ import annotations

import time

import pytest


def wait_for_backup(client, backup_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/v1/backups/{backup_id}").json()
        if data["status"] not in ("pending", "running"):
            return data
        time.sleep(0.25)
    raise AssertionError(f"backup {backup_id} did not finish in time")


def make_job(client, name, path, **overrides):
    payload = {
        "name": name,
        "description": "test job",
        "compression": "tar.gz",
        "compression_level": 6,
        "sources": [{"name": "src", "path": str(path), "enabled": True,
                     "exclude_patterns": ["*.log"]}],
        "schedule": {"schedule_type": "manual"},
        "retention_keep_last": 5,
    }
    payload.update(overrides)
    r = client.post("/api/v1/jobs", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_setup_required_flag(client):
    r = client.get("/api/v1/auth/status")
    assert r.status_code == 200
    assert "setup_required" in r.json()


def test_unauthenticated_access_denied(client):
    fresh = client.__class__(client.app)
    assert fresh.get("/api/v1/jobs").status_code == 401
    assert fresh.get("/api/v1/dashboard").status_code == 401
    assert fresh.get("/api/v1/users").status_code == 401


def test_login_wrong_password(admin_client):
    fresh = admin_client.__class__(admin_client.app)
    r = fresh.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_me_returns_csrf(admin_client):
    r = admin_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["csrf_token"]
    assert r.json()["user"]["role_name"] == "admin"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def test_csrf_required_for_mutation(admin_client):
    """A cookie-authenticated POST without the CSRF header must be rejected."""
    csrf = admin_client.headers.pop("X-CSRF-Token")
    try:
        r = admin_client.post("/api/v1/jobs", json={"name": "csrf", "sources": [{"path": "/tmp"}]})
        assert r.status_code == 403, r.text
        assert "CSRF" in r.json()["detail"]
    finally:
        admin_client.headers["X-CSRF-Token"] = csrf


def test_csrf_not_required_for_reads(admin_client):
    assert admin_client.get("/api/v1/jobs").status_code == 200


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def test_job_crud(admin_client, sample_tree):
    job = make_job(admin_client, "CRUD Job", sample_tree)
    assert job["id"] and job["name"] == "CRUD Job"
    assert len(job["sources"]) == 1

    r = admin_client.get(f"/api/v1/jobs/{job['id']}")
    assert r.status_code == 200

    r = admin_client.put(f"/api/v1/jobs/{job['id']}", json={
        "name": "CRUD Job Renamed",
        "compression": "zip",
        "sources": [{"path": str(sample_tree), "enabled": True, "exclude_patterns": []}],
        "schedule": {"schedule_type": "daily", "hour": 4, "minute": 15},
    })
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "CRUD Job Renamed"
    assert r.json()["compression"] == "zip"
    assert r.json()["next_run_at"] is not None

    r = admin_client.delete(f"/api/v1/jobs/{job['id']}")
    assert r.status_code == 200
    assert admin_client.get(f"/api/v1/jobs/{job['id']}").status_code == 404


def test_duplicate_job_name_rejected(admin_client, sample_tree):
    make_job(admin_client, "Dup Job", sample_tree)
    r = admin_client.post("/api/v1/jobs", json={
        "name": "Dup Job", "sources": [{"path": str(sample_tree)}],
    })
    assert r.status_code == 409


def test_job_requires_source(admin_client):
    r = admin_client.post("/api/v1/jobs", json={"name": "No Sources", "sources": []})
    assert r.status_code == 400


def test_many_sources(admin_client, tmp_path):
    paths = []
    for i in range(40):
        d = tmp_path / f"dir{i}"
        d.mkdir()
        (d / "f.txt").write_text("x")
        paths.append(str(d))
    job = make_job(admin_client, "Many Sources", tmp_path,
                   sources=[{"path": p, "enabled": True} for p in paths])
    assert len(job["sources"]) == 40


def test_invalid_source_path_rejected(admin_client):
    r = admin_client.post("/api/v1/jobs", json={
        "name": "Relative", "sources": [{"path": "relative/path"}],
    })
    assert r.status_code == 422


def test_invalid_cron_rejected(admin_client, sample_tree):
    r = admin_client.post("/api/v1/jobs", json={
        "name": "Bad Cron",
        "sources": [{"path": str(sample_tree)}],
        "schedule": {"schedule_type": "cron", "cron_expression": "not a cron"},
    })
    assert r.status_code == 422


def test_duplicate_job(admin_client, sample_tree):
    job = make_job(admin_client, "Original", sample_tree)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/duplicate")
    assert r.status_code == 200
    assert r.json()["name"].startswith("Original (copy)")
    assert r.json()["enabled"] is False


def test_pause_resume_toggle(admin_client, sample_tree):
    job = make_job(admin_client, "Pausable", sample_tree,
                   schedule={"schedule_type": "daily", "hour": 1, "minute": 0})
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/pause")
    assert r.status_code == 200 and r.json()["next_run_at"] is None
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/resume")
    assert r.json()["next_run_at"] is not None
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/toggle")
    assert r.json()["enabled"] is False


# ---------------------------------------------------------------------------
# Backup execution
# ---------------------------------------------------------------------------
def test_run_backup_and_inspect(admin_client, sample_tree):
    job = make_job(admin_client, "Run Test", sample_tree)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    assert r.status_code == 200
    backup = wait_for_backup(admin_client, r.json()["backup_id"])

    assert backup["status"] == "success", backup["error_message"]
    assert backup["verified"] is True
    assert backup["archive_size"] > 0
    assert backup["file_count"] >= 3
    assert len(backup["checksum"]) == 64, "SHA-256 checksum must be recorded"

    r = admin_client.get(f"/api/v1/backups/{backup['id']}/archive")
    entries = r.json()["items"]
    assert entries
    assert not any(e["path"].endswith(".log") for e in entries)

    r = admin_client.get(f"/api/v1/backups/{backup['id']}/files")
    assert r.json()["total"] >= 3


def test_overlap_prevented(admin_client, sample_tree):
    job = make_job(admin_client, "Overlap", sample_tree)
    first = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    second = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    assert first.status_code == 200
    assert second.status_code == 409
    wait_for_backup(admin_client, first.json()["backup_id"])


def test_backup_missing_source_fails_honestly(admin_client, tmp_path):
    missing = tmp_path / "does-not-exist"
    job = make_job(admin_client, "Missing Source", missing)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    backup = wait_for_backup(admin_client, r.json()["backup_id"])
    assert backup["status"] == "failed"
    assert "No files" in backup["error_message"]


def test_encrypted_backup(admin_client, sample_tree):
    job = make_job(admin_client, "Encrypted", sample_tree,
                   encrypt_archive=True, encryption_password="ArchivePass123")
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    backup = wait_for_backup(admin_client, r.json()["backup_id"])
    assert backup["status"] == "success", backup["error_message"]
    assert backup["archive_name"].endswith(".enc")
    assert backup["verified"] is True

    # Archive listing requires the stored password and must work
    r = admin_client.get(f"/api/v1/backups/{backup['id']}/archive")
    assert r.status_code == 200 and r.json()["items"]


def test_retention_prunes_old_backups(admin_client, sample_tree):
    job = make_job(admin_client, "Retention", sample_tree, retention_keep_last=2)
    ids = []
    for _ in range(4):
        r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
        b = wait_for_backup(admin_client, r.json()["backup_id"])
        assert b["status"] == "success"
        ids.append(b["id"])
    remaining = admin_client.get(f"/api/v1/backups?job_id={job['id']}&status=success&limit=100").json()
    assert remaining["total"] <= 2


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def test_restore_roundtrip(admin_client, sample_tree, tmp_path):
    job = make_job(admin_client, "Restore Test", sample_tree)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    backup = wait_for_backup(admin_client, r.json()["backup_id"])

    dest = tmp_path / "restored"
    r = admin_client.post(f"/api/v1/backups/{backup['id']}/restore", json={
        "destination": str(dest), "selected_paths": [], "overwrite": False,
        "create_safety_backup": False,
    })
    assert r.status_code == 200, r.text
    restore_id = r.json()["restore_id"]

    deadline = time.time() + 60
    while time.time() < deadline:
        data = admin_client.get(f"/api/v1/restores/{restore_id}").json()
        if data["status"] not in ("pending", "running"):
            break
        time.sleep(0.25)
    assert data["status"] == "success", data["error_message"]
    assert data["restored_files"] >= 3
    assert any(p.name == "index.html" for p in dest.rglob("*"))


def test_restore_rejects_traversal(admin_client, sample_tree, tmp_path):
    job = make_job(admin_client, "Traversal", sample_tree)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    backup = wait_for_backup(admin_client, r.json()["backup_id"])
    r = admin_client.post(f"/api/v1/backups/{backup['id']}/restore", json={
        "destination": str(tmp_path / "x"), "selected_paths": ["../../etc/passwd"],
    })
    assert r.status_code == 422


def test_restore_requires_absolute_destination(admin_client, sample_tree):
    job = make_job(admin_client, "Abs Dest", sample_tree)
    r = admin_client.post(f"/api/v1/jobs/{job['id']}/run")
    backup = wait_for_backup(admin_client, r.json()["backup_id"])
    r = admin_client.post(f"/api/v1/backups/{backup['id']}/restore", json={"destination": "relative"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_viewer_cannot_write(admin_client):
    r = admin_client.post("/api/v1/users", json={
        "username": "viewer_t", "password": "ViewerPass123", "role": "viewer",
    })
    assert r.status_code in (200, 409)

    viewer = admin_client.__class__(admin_client.app)
    r = viewer.post("/api/v1/auth/login", json={"username": "viewer_t", "password": "ViewerPass123"})
    assert r.status_code == 200
    viewer.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})

    assert viewer.get("/api/v1/jobs").status_code == 200
    r = viewer.post("/api/v1/jobs", json={"name": "nope", "sources": [{"path": "/tmp"}]})
    assert r.status_code == 403
    assert viewer.get("/api/v1/users").status_code == 403


def test_operator_can_run_but_not_manage_users(admin_client, sample_tree):
    admin_client.post("/api/v1/users", json={
        "username": "operator_t", "password": "OperatorPass123", "role": "operator",
    })
    op = admin_client.__class__(admin_client.app)
    r = op.post("/api/v1/auth/login", json={"username": "operator_t", "password": "OperatorPass123"})
    op.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    assert op.get("/api/v1/users").status_code == 403
    job = make_job(admin_client, "Operator Run", sample_tree)
    r = op.post(f"/api/v1/jobs/{job['id']}/run")
    assert r.status_code == 200
    wait_for_backup(admin_client, r.json()["backup_id"])


def test_cannot_delete_last_admin(admin_client):
    me = admin_client.get("/api/v1/auth/me").json()["user"]
    r = admin_client.delete(f"/api/v1/users/{me['id']}")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Settings / misc
# ---------------------------------------------------------------------------
def test_settings_read_write(admin_client):
    r = admin_client.get("/api/v1/settings")
    assert r.status_code == 200
    r = admin_client.put("/api/v1/settings", json={"values": {"min_free_disk_mb": "256"}})
    assert r.status_code == 200
    r = admin_client.get("/api/v1/settings")
    assert r.json()["values"]["min_free_disk_mb"] == "256"


def test_health_endpoint(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_shape(admin_client):
    r = admin_client.get("/api/v1/dashboard")
    assert r.status_code == 200
    data = r.json()
    for key in ("stats", "disk", "system", "activity_series", "recent_backups", "scheduler"):
        assert key in data
    assert len(data["activity_series"]) == 14


def test_monitoring(admin_client):
    r = admin_client.get("/api/v1/monitoring")
    assert r.status_code == 200
    data = r.json()
    assert "cpu" in data and "memory" in data and "disk" in data


def test_storage_crud_and_test(admin_client, tmp_path):
    target = tmp_path / "storage"
    r = admin_client.post("/api/v1/storage", json={
        "name": "Test Local", "storage_type": "local", "config": {"path": str(target)},
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = admin_client.post(f"/api/v1/storage/{sid}/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    r = admin_client.delete(f"/api/v1/storage/{sid}")
    assert r.status_code == 200


def test_telegram_destination_validation(admin_client):
    r = admin_client.post("/api/v1/telegram", json={
        "name": "Bad Bot", "bot_token": "not-a-token", "chat_id": "123",
    })
    assert r.status_code == 200
    tid = r.json()["id"]
    r = admin_client.post(f"/api/v1/telegram/{tid}/test")
    assert r.status_code == 200
    assert r.json()["ok"] is False  # honest failure, not a fake success
    admin_client.delete(f"/api/v1/telegram/{tid}")


def test_notification_settings(admin_client):
    r = admin_client.get("/api/v1/notifications/settings")
    assert r.status_code == 200
    assert len(r.json()) >= 8
    r = admin_client.put("/api/v1/notifications/settings", json={
        "event": "backup_completed", "in_app": True, "telegram": False,
        "email": False, "enabled": True,
    })
    assert r.status_code == 200


def test_activity_logs(admin_client):
    r = admin_client.get("/api/v1/logs?limit=10")
    assert r.status_code == 200
    assert "items" in r.json()


def test_export_backups(admin_client):
    r = admin_client.get("/api/v1/backups/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    r = admin_client.get("/api/v1/backups/export?format=json")
    assert r.status_code == 200


def test_security_headers(admin_client):
    r = admin_client.get("/api/v1/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in r.headers


def test_login_rate_limit_and_lockout(admin_client):
    fresh = admin_client.__class__(admin_client.app)
    admin_client.post("/api/v1/users", json={
        "username": "lockme", "password": "LockMePass123", "role": "viewer",
    })
    for _ in range(5):
        fresh.post("/api/v1/auth/login", json={"username": "lockme", "password": "bad"})
    r = fresh.post("/api/v1/auth/login", json={"username": "lockme", "password": "LockMePass123"})
    assert r.status_code == 401
    assert "locked" in r.json()["detail"].lower()


def test_persistence_across_restart(tmp_path):
    """Settings and history survive a new app instance (same DB file)."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "AdminPass123"})
        assert r.status_code == 200
        c.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
        jobs = c.get("/api/v1/jobs").json()
        assert len(jobs) > 0
        backups = c.get("/api/v1/backups").json()
        assert backups["total"] > 0
