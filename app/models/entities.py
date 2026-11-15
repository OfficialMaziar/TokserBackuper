"""ORM entities for Tokser Backup Manager."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class RoleName(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class JobStatus(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


class BackupStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class RestoreStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupMode(str, enum.Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class StorageType(str, enum.Enum):
    LOCAL = "local"
    SFTP = "sftp"
    FTP = "ftp"
    S3 = "s3"
    MINIO = "minio"


class ScheduleType(str, enum.Enum):
    MANUAL = "manual"
    MINUTES = "minutes"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


class DatabaseType(str, enum.Enum):
    MYSQL = "mysql"
    MARIADB = "mariadb"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)

    users: Mapped[list["User"]] = relationship(back_populates="role")


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str] = mapped_column(String(255), default="")
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str] = mapped_column(String(64), default="")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")
    sessions: Mapped[list["SessionToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_name(self) -> str:
        return self.role.name if self.role else ""


class SessionToken(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="sessions")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ---------------------------------------------------------------------------
# Jobs / sources / schedules
# ---------------------------------------------------------------------------
class BackupJob(Base, TimestampMixin):
    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.IDLE.value)

    compression: Mapped[str] = mapped_column(String(16), default="tar.gz")
    compression_level: Mapped[int] = mapped_column(Integer, default=6)
    backup_mode: Mapped[str] = mapped_column(String(16), default=BackupMode.FULL.value)

    storage_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_destinations.id", ondelete="SET NULL"), nullable=True
    )
    telegram_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_destinations.id", ondelete="SET NULL"), nullable=True
    )
    telegram_upload_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    retention_keep_last: Mapped[int | None] = mapped_column(Integer, default=10)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    encrypt_archive: Mapped[bool] = mapped_column(Boolean, default=False)
    encryption_password_enc: Mapped[str] = mapped_column(Text, default="")

    follow_symlinks: Mapped[bool] = mapped_column(Boolean, default=False)
    preserve_permissions: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    success_runs: Mapped[int] = mapped_column(Integer, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0)

    sources: Mapped[list["BackupSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    schedule: Mapped["Schedule | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    database_sources: Mapped[list["DatabaseSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    history: Mapped[list["BackupHistory"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class BackupSource(Base, TimestampMixin):
    __tablename__ = "backup_sources"
    __table_args__ = (UniqueConstraint("job_id", "path", name="uq_source_job_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("backup_jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    estimated_size: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)

    job: Mapped[BackupJob] = relationship(back_populates="sources")


class Schedule(Base, TimestampMixin):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("backup_jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    schedule_type: Mapped[str] = mapped_column(String(16), default=ScheduleType.MANUAL.value)
    interval_value: Mapped[int] = mapped_column(Integer, default=1)
    hour: Mapped[int] = mapped_column(Integer, default=3)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    day_of_week: Mapped[int] = mapped_column(Integer, default=1)  # 0=Mon .. 6=Sun
    day_of_month: Mapped[int] = mapped_column(Integer, default=1)
    cron_expression: Mapped[str] = mapped_column(String(128), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    last_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[BackupJob] = relationship(back_populates="schedule")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
class BackupHistory(Base, TimestampMixin):
    __tablename__ = "backup_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("backup_jobs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    job_name: Mapped[str] = mapped_column(String(128), default="")
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default=BackupStatus.PENDING.value, index=True)
    mode: Mapped[str] = mapped_column(String(16), default=BackupMode.FULL.value)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    source_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    archive_name: Mapped[str] = mapped_column(String(255), default="")
    archive_path: Mapped[str] = mapped_column(String(1024), default="")
    archive_size: Mapped[int] = mapped_column(Integer, default=0)
    source_size: Mapped[int] = mapped_column(Integer, default=0)
    compression_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(128), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    storage_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_destinations.id", ondelete="SET NULL"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(String(1024), default="")
    telegram_status: Mapped[str] = mapped_column(String(32), default="")
    telegram_parts: Mapped[int] = mapped_column(Integer, default=0)
    telegram_parts_sent: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str] = mapped_column(Text, default="")
    log_path: Mapped[str] = mapped_column(String(1024), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("backup_history.id", ondelete="SET NULL"), nullable=True
    )

    job: Mapped[BackupJob | None] = relationship(back_populates="history")
    files: Mapped[list["BackupFile"]] = relationship(
        back_populates="backup", cascade="all, delete-orphan"
    )


class BackupFile(Base):
    __tablename__ = "backup_files"
    __table_args__ = (Index("ix_backup_files_backup_path", "backup_id", "path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backup_id: Mapped[int] = mapped_column(
        ForeignKey("backup_history.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0.0)
    checksum: Mapped[str] = mapped_column(String(128), default="")

    backup: Mapped[BackupHistory] = relationship(back_populates="files")


class RestoreHistory(Base, TimestampMixin):
    __tablename__ = "restore_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backup_id: Mapped[int | None] = mapped_column(
        ForeignKey("backup_history.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RestoreStatus.PENDING.value, index=True)
    destination: Mapped[str] = mapped_column(String(1024), default="")
    selected_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    overwrite: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_files: Mapped[int] = mapped_column(Integer, default=0)
    restored_bytes: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_path: Mapped[str] = mapped_column(String(2048), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    safety_backup_path: Mapped[str] = mapped_column(String(1024), default="")
    safety_backup_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Storage / Telegram
# ---------------------------------------------------------------------------
class StorageDestination(Base, TimestampMixin):
    __tablename__ = "storage_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(16), default=StorageType.LOCAL.value)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Non-secret config (host, port, bucket, path, username ...)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Encrypted secrets (password, access_key, secret_key ...)
    secrets_enc: Mapped[str] = mapped_column(Text, default="")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, default="")


class TelegramDestination(Base, TimestampMixin):
    __tablename__ = "telegram_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    bot_token_enc: Mapped[str] = mapped_column(Text, default="")
    chat_id: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    send_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    upload_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class NotificationSetting(Base, TimestampMixin):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    link: Mapped[str] = mapped_column(String(255), default="")


# ---------------------------------------------------------------------------
# Logs / settings / servers / databases
# ---------------------------------------------------------------------------
class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)


class Server(Base, TimestampMixin):
    """Registered server. Local is always present; remote agents are a
    documented roadmap item and this table stores their registration."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatabaseSource(Base, TimestampMixin):
    __tablename__ = "database_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("backup_jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    db_type: Mapped[str] = mapped_column(String(16), default=DatabaseType.MYSQL.value)
    host: Mapped[str] = mapped_column(String(255), default="localhost")
    port: Mapped[int] = mapped_column(Integer, default=0)
    database_name: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    password_enc: Mapped[str] = mapped_column(Text, default="")
    sqlite_path: Mapped[str] = mapped_column(String(1024), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    job: Mapped[BackupJob] = relationship(back_populates="database_sources")
