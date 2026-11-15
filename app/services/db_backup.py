"""Database dump helpers for MySQL/MariaDB, PostgreSQL and SQLite.

Dumps are produced with the vendor tools using argument lists (never a
shell), so credentials and database names cannot be injected. Passwords are
passed through environment variables or option files, never on the command
line where they would appear in ``ps`` output.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_PORTS = {"mysql": 3306, "mariadb": 3306, "postgresql": 5432}


class DatabaseBackupError(RuntimeError):
    pass


@dataclass
class DumpResult:
    path: str
    size: int
    command: str


def _run(cmd: list[str], env: dict[str, str] | None = None, timeout: int = 3600) -> None:
    log.info("Running database dump: %s", cmd[0])
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DatabaseBackupError(f"Dump tool not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DatabaseBackupError("Database dump timed out") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace")[:800]
        raise DatabaseBackupError(f"Dump command failed ({proc.returncode}): {stderr}")


def dump_database(
    *,
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    sqlite_path: str,
    out_dir: str | Path,
    name: str = "",
) -> DumpResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_type = (db_type or "").lower()
    safe = "".join(c for c in (name or database or "db") if c.isalnum() or c in "._-") or "db"

    if db_type in {"mysql", "mariadb"}:
        return _dump_mysql(host, port, database, username, password, out_dir, safe)
    if db_type == "postgresql":
        return _dump_postgres(host, port, database, username, password, out_dir, safe)
    if db_type == "sqlite":
        return _dump_sqlite(sqlite_path, out_dir, safe)
    raise DatabaseBackupError(f"Unsupported database type: {db_type}")


def _dump_mysql(host, port, database, username, password, out_dir: Path, safe: str) -> DumpResult:
    tool = shutil.which("mysqldump") or shutil.which("mariadb-dump")
    if not tool:
        raise DatabaseBackupError("mysqldump / mariadb-dump is not installed")
    if not database:
        raise DatabaseBackupError("Database name is required")
    out = out_dir / f"{safe}_{_ts()}.sql"
    # Credentials go in a temporary option file (0600) to avoid ps leakage.
    fd, cnf = tempfile.mkstemp(prefix="tbm_my_", suffix=".cnf")
    os.close(fd)
    try:
        os.chmod(cnf, 0o600)
        with open(cnf, "w", encoding="utf-8") as fh:
            fh.write("[client]\n")
            fh.write(f"host={host or 'localhost'}\n")
            fh.write(f"port={port or DEFAULT_PORTS['mysql']}\n")
            fh.write(f"user={username}\n")
            if password:
                fh.write(f"password={password}\n")
        cmd = [
            tool,
            f"--defaults-extra-file={cnf}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--events",
            "--no-tablespaces",
            "--result-file",
            str(out),
            database,
        ]
        _run(cmd)
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass
    if not out.exists() or out.stat().st_size == 0:
        raise DatabaseBackupError("mysqldump produced an empty file")
    return DumpResult(str(out), out.stat().st_size, "mysqldump")


def _dump_postgres(host, port, database, username, password, out_dir: Path, safe: str) -> DumpResult:
    tool = shutil.which("pg_dump")
    if not tool:
        raise DatabaseBackupError("pg_dump is not installed")
    if not database:
        raise DatabaseBackupError("Database name is required")
    out = out_dir / f"{safe}_{_ts()}.sql"
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    cmd = [
        tool,
        "--host", host or "localhost",
        "--port", str(port or DEFAULT_PORTS["postgresql"]),
        "--username", username or "postgres",
        "--no-password",
        "--format=plain",
        "--no-owner",
        "--no-privileges",
        "--file", str(out),
        database,
    ]
    _run(cmd, env=env)
    if not out.exists() or out.stat().st_size == 0:
        raise DatabaseBackupError("pg_dump produced an empty file")
    return DumpResult(str(out), out.stat().st_size, "pg_dump")


def _dump_sqlite(sqlite_path: str, out_dir: Path, safe: str) -> DumpResult:
    if not sqlite_path:
        raise DatabaseBackupError("SQLite file path is required")
    src = Path(sqlite_path)
    if not src.exists():
        raise DatabaseBackupError(f"SQLite database not found: {sqlite_path}")
    out = out_dir / f"{safe}_{_ts()}.sqlite"
    # Use SQLite's online backup API for a consistent snapshot even while hot.
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source:
            with sqlite3.connect(str(out)) as dest:
                source.backup(dest)
    except sqlite3.Error as exc:
        raise DatabaseBackupError(f"SQLite backup failed: {exc}") from exc
    if not out.exists() or out.stat().st_size == 0:
        raise DatabaseBackupError("SQLite backup produced an empty file")
    return DumpResult(str(out), out.stat().st_size, "sqlite-backup-api")


def _ts() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
