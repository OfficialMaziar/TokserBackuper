"""Test fixtures. Each test session gets an isolated data directory and DB."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Configure an isolated environment BEFORE importing the app.
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="tbm_tests_"))
os.environ["TBM_DATA_DIR"] = str(_TMP_ROOT / "data")
os.environ["TBM_BACKUP_DIR"] = str(_TMP_ROOT / "backups")
os.environ["TBM_LOG_DIR"] = str(_TMP_ROOT / "logs")
os.environ["TBM_DATABASE_URL"] = f"sqlite:///{(_TMP_ROOT / 'data' / 'test.db').as_posix()}"
os.environ["TBM_SCHEDULER"] = "false"
os.environ["TBM_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["TBM_ENCRYPTION_KEY"] = "test-encryption-key-not-for-production"
os.environ["TBM_RATE_LIMIT"] = "100000"


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP_ROOT


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_client(client):
    """A client with an authenticated administrator session."""
    r = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "AdminPass123", "email": "admin@example.com",
              "full_name": "Administrator"},
    )
    if r.status_code == 409:
        r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "AdminPass123"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf})
    return client


@pytest.fixture()
def sample_tree(tmp_path) -> Path:
    root = tmp_path / "source"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "index.html").write_text("<h1>hello</h1>" * 50, encoding="utf-8")
    (root / "sub" / "app.js").write_text("console.log('x');" * 100, encoding="utf-8")
    (root / "sub" / "deep" / "data.bin").write_bytes(bytes(range(256)) * 8)
    (root / "sub" / "debug.log").write_text("noise", encoding="utf-8")
    (root / "cache.tmp").write_text("temp", encoding="utf-8")
    return root


@pytest.fixture(scope="session", autouse=True)
def cleanup_session():
    yield
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
