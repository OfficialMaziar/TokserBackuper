# Changelog

All notable changes to Tokser Backup Manager are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-11-12

First production release.

### Added

**Backup engine**
- Unlimited sources per job — files, directories and database dumps
- Per-source and per-job exclusion patterns with directory pruning
- TAR, TAR.GZ, ZIP and Zstandard archive formats with configurable levels
- AES-256-GCM archive encryption with chunked streaming
- Post-creation verification reading every member to EOF
- SHA-256 checksums recorded per archive and per-file metadata in `backup_files`
- Streaming implementation that never loads archives into RAM
- Cooperative cancellation with automatic partial-file cleanup
- Preservation of permissions, ownership, timestamps and symlinks
- Global concurrency limit and per-job overlap prevention

**Scheduling**
- Manual, minute, hourly, daily, weekly, monthly and cron schedules
- Dependency-free 5-field cron parser with ranges, lists, steps and names
- Per-job timezone with DST-aware next-run computation and start/end dates
- Persisted next-run times so schedules survive restarts
- Scheduler status surfaced in the panel and API

**Recovery**
- Archive content browsing from the real file on disk
- Full and selective restore by path
- Zip Slip and path traversal protection
- Optional safety backup of the destination before overwriting
- Live restore progress and history

**Retention**
- Keep-last-N and keep-for-N-days policies, per job
- Automatic pruning after each successful run, with remote copy deletion
- Newest successful backup and running backups are never removed

**Delivery**
- Local, SFTP, FTP/FTPS and S3-compatible storage backends
- Native S3 SigV4 signing with multipart upload (no boto3 dependency)
- Telegram Bot API integration with automatic archive splitting
- Per-part retry with exponential backoff and honest aggregate status
- Support for a self-hosted local Bot API server
- Encrypted credentials at rest

**Database backups**
- MySQL/MariaDB via `mysqldump`/`mariadb-dump` with consistent snapshots
- PostgreSQL via `pg_dump`
- SQLite via the online backup API
- Credentials passed through option files or environment, never the command line

**Security**
- Argon2id password hashing with bcrypt fallback and transparent re-hashing
- Server-side sessions storing only token hashes
- Middleware-enforced CSRF protection for all mutating requests
- Login rate limiting and per-account lockout
- Role-based access control with three roles and granular permissions
- Comprehensive audit logging
- Security headers and a restrictive Content-Security-Policy
- TOTP two-factor verification

**Interface**
- Modern responsive panel with dark and light themes and custom accent colours
- Full RTL Persian interface alongside English
- Dashboard with live statistics and four chart types
- Server monitoring page with CPU, memory, disk, I/O, network and uptime
- Purpose-built SVG chart library with crosshair tooltips and data tables
- Toast notifications, modal dialogs, live progress and skeleton loaders

**Operations**
- Automated installer for Ubuntu and Debian
- Safe uninstaller that preserves backups unless explicitly purged
- Hardened systemd unit with graceful shutdown
- Dockerfile and Docker Compose deployment
- Alembic migration baseline
- Health check endpoint and script
- CSV/JSON backup history export and log download

### Known limitations

- Incremental and differential backups: metadata model present, engine performs
  full backups only. Not exposed as a working feature.
- Multi-server remote agents: registration table exists; agent transport is not
  implemented.
- Two-factor enrollment UI: verification is implemented and enforced; the QR
  enrollment screen is not yet built.

[1.0.0]: https://github.com/OfficialMaziar/TokserBackuper/releases/tag/v1.0.0
