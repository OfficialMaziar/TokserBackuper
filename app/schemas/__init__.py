"""Pydantic schemas for API request/response validation."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.entities import (
    BackupMode,
    DatabaseType,
    ScheduleType,
    StorageType,
)

VALID_COMPRESSION = {"tar", "tar.gz", "zip", "zst"}
CRON_FIELD = re.compile(r"^[\d*/,\-\sA-Za-z]+$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=10, max_length=256)
    email: str = Field(default="", max_length=255)
    full_name: str = Field(default="", max_length=128)

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("Password must be at least 10 characters")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain letters and digits")
        return v


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str = Field(default="", max_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=10, max_length=256)
    email: str = Field(default="", max_length=255)
    full_name: str = Field(default="", max_length=128)
    role: Literal["admin", "operator", "viewer"] = "viewer"
    is_active: bool = True


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "operator", "viewer"] | None = None
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    totp_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    role_name: str = ""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
class SourceIn(BaseModel):
    name: str = Field(default="", max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    enabled: bool = True
    exclude_patterns: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def clean_path(cls, v: str) -> str:
        v = v.strip()
        if "\x00" in v:
            raise ValueError("Invalid path")
        if not v.startswith("/") and not re.match(r"^[A-Za-z]:[\\/]", v):
            raise ValueError("Path must be absolute")
        return v.rstrip("/") or "/"

    @field_validator("exclude_patterns")
    @classmethod
    def limit_patterns(cls, v: list[str]) -> list[str]:
        if len(v) > 200:
            raise ValueError("Too many exclude patterns")
        return [p.strip() for p in v if p.strip()][:200]


class SourceOut(ORMModel):
    id: int
    name: str
    path: str
    enabled: bool
    exclude_patterns: list[str]
    estimated_size: int
    available: bool
    last_checked_at: datetime | None


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
class ScheduleIn(BaseModel):
    schedule_type: ScheduleType = ScheduleType.MANUAL
    interval_value: int = Field(default=1, ge=1, le=100000)
    hour: int = Field(default=3, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: int = Field(default=1, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=31)
    cron_expression: str = Field(default="", max_length=128)
    timezone: str = Field(default="UTC", max_length=64)
    start_date: datetime | None = None
    end_date: datetime | None = None
    paused: bool = False

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str, info) -> str:
        v = v.strip()
        if not v:
            return v
        if len(v.split()) != 5 or not CRON_FIELD.match(v):
            raise ValueError("Cron expression must have 5 fields")
        # Reject expressions the scheduler could never satisfy.
        from app.services.cron import CronError, CronExpression

        try:
            CronExpression(v)
        except CronError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Reject unknown timezones instead of silently falling back to UTC."""
        v = (v or "UTC").strip() or "UTC"
        if v.upper() == "UTC":
            return "UTC"
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {v}") from exc
        return v

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class ScheduleOut(ORMModel):
    id: int
    schedule_type: str
    interval_value: int
    hour: int
    minute: int
    day_of_week: int
    day_of_month: int
    cron_expression: str
    timezone: str
    start_date: datetime | None
    end_date: datetime | None
    paused: bool


# ---------------------------------------------------------------------------
# Database source
# ---------------------------------------------------------------------------
class DatabaseSourceIn(BaseModel):
    name: str = Field(default="", max_length=128)
    db_type: DatabaseType = DatabaseType.MYSQL
    host: str = Field(default="localhost", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    database_name: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=512)
    sqlite_path: str = Field(default="", max_length=1024)
    enabled: bool = True

    @field_validator("sqlite_path")
    @classmethod
    def abs_sqlite(cls, v: str) -> str:
        if v and not v.startswith("/") and not re.match(r"^[A-Za-z]:[\\/]", v):
            raise ValueError("SQLite path must be absolute")
        return v


class DatabaseSourceOut(ORMModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    sqlite_path: str
    enabled: bool


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    compression: str = "tar.gz"
    compression_level: int = Field(default=6, ge=1, le=19)
    backup_mode: BackupMode = BackupMode.FULL
    storage_destination_id: int | None = None
    telegram_destination_id: int | None = None
    telegram_upload_enabled: bool = False
    retention_keep_last: int | None = Field(default=10, ge=0, le=10000)
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    encrypt_archive: bool = False
    encryption_password: str = Field(default="", max_length=512)
    follow_symlinks: bool = False
    preserve_permissions: bool = True
    exclude_patterns: list[str] = Field(default_factory=list)
    sources: list[SourceIn] = Field(default_factory=list)
    database_sources: list[DatabaseSourceIn] = Field(default_factory=list)
    schedule: ScheduleIn | None = None

    @field_validator("compression")
    @classmethod
    def compression_ok(cls, v: str) -> str:
        if v not in VALID_COMPRESSION:
            raise ValueError(f"Compression must be one of {sorted(VALID_COMPRESSION)}")
        return v

    @field_validator("sources")
    @classmethod
    def unique_paths(cls, v: list[SourceIn]) -> list[SourceIn]:
        """Reject duplicate paths within one job.

        The database enforces this too (uq_source_job_path); catching it here
        produces a field-level message instead of an integrity error.
        """
        seen: set[str] = set()
        for src in v:
            if src.path in seen:
                raise ValueError(f"Duplicate source path: {src.path}")
            seen.add(src.path)
        return v


class JobOut(ORMModel):
    id: int
    name: str
    description: str
    enabled: bool
    status: str
    compression: str
    compression_level: int
    backup_mode: str
    storage_destination_id: int | None
    telegram_destination_id: int | None
    telegram_upload_enabled: bool
    retention_keep_last: int | None
    retention_days: int | None
    encrypt_archive: bool
    follow_symlinks: bool
    preserve_permissions: bool
    exclude_patterns: list[str]
    last_run_at: datetime | None
    last_status: str
    last_error: str
    next_run_at: datetime | None
    total_runs: int
    success_runs: int
    failed_runs: int
    created_at: datetime
    sources: list[SourceOut] = Field(default_factory=list)
    schedule: ScheduleOut | None = None
    database_sources: list[DatabaseSourceOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Backup history
# ---------------------------------------------------------------------------
class BackupOut(ORMModel):
    id: int
    job_id: int | None
    job_name: str
    trigger: str
    status: str
    mode: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float
    archive_name: str
    archive_size: int
    source_size: int
    compression_ratio: float
    file_count: int
    checksum: str = ""
    verified: bool
    storage_path: str
    telegram_status: str
    telegram_parts: int
    telegram_parts_sent: int
    error_message: str
    progress: int
    created_at: datetime


class BackupFileOut(ORMModel):
    id: int
    path: str
    size: int
    mtime: float


class RestoreRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=1024)
    selected_paths: list[str] = Field(default_factory=list)
    overwrite: bool = False
    create_safety_backup: bool = True
    preserve_permissions: bool = True

    @field_validator("destination")
    @classmethod
    def abs_dest(cls, v: str) -> str:
        v = v.strip()
        if "\x00" in v:
            raise ValueError("Invalid destination")
        if not v.startswith("/") and not re.match(r"^[A-Za-z]:[\\/]", v):
            raise ValueError("Destination must be absolute")
        return v.rstrip("/") or "/"

    @field_validator("selected_paths")
    @classmethod
    def no_traversal(cls, v: list[str]) -> list[str]:
        for p in v:
            if ".." in p.split("/") or p.startswith("/") or "\x00" in p:
                raise ValueError(f"Invalid archive path: {p}")
        return v


class RestoreOut(ORMModel):
    id: int
    backup_id: int | None
    status: str
    destination: str
    selected_paths: list[str]
    overwrite: bool
    started_at: datetime | None
    finished_at: datetime | None
    restored_files: int
    restored_bytes: int
    error_message: str


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
class StorageIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    storage_type: StorageType = StorageType.LOCAL
    enabled: bool = True
    is_default: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class StorageOut(ORMModel):
    id: int
    name: str
    storage_type: str
    enabled: bool
    is_default: bool
    config: dict[str, Any]
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str


class StorageTestResult(BaseModel):
    ok: bool
    message: str
    capacity: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
class TelegramIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    bot_token: str = Field(default="", max_length=512)
    chat_id: str = Field(default="", max_length=64)
    enabled: bool = True
    send_notifications: bool = True
    upload_enabled: bool = True


class TelegramOut(ORMModel):
    id: int
    name: str
    chat_id: str
    enabled: bool
    send_notifications: bool
    upload_enabled: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str
    bot_token_masked: str = ""


class TelegramTestRequest(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None


# ---------------------------------------------------------------------------
# Notifications / settings
# ---------------------------------------------------------------------------
class NotificationSettingIn(BaseModel):
    event: str
    in_app: bool = True
    telegram: bool = True
    email: bool = False
    enabled: bool = True


class NotificationSettingOut(ORMModel):
    id: int
    event: str
    in_app: bool
    telegram: bool
    email: bool
    enabled: bool


class NotificationOut(ORMModel):
    id: int
    event: str
    level: str
    title: str
    message: str
    read: bool
    link: str
    created_at: datetime


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class ActivityOut(ORMModel):
    id: int
    username: str
    action: str
    entity_type: str
    entity_id: str
    detail: str
    ip_address: str
    level: str
    created_at: datetime
