# Tokser Backup Manager

**Enterprise-grade Linux backup and recovery management platform.**

Developed and maintained by **TokserTeam**.

Tokser Backup Manager (TBM) is a self-hosted backup platform for Linux servers.
It gives you a modern web panel to define unlimited backup sources, schedule
independent jobs, produce compressed and optionally encrypted archives, deliver
them to remote storage or Telegram, restore files selectively, and audit
everything that happens.

---

## Table of contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Automated installer (Ubuntu / Debian)](#automated-installer-ubuntu--debian)
  - [Docker](#docker)
  - [Manual installation](#manual-installation)
- [Configuration](#configuration)
- [First run](#first-run)
- [Usage](#usage)
  - [Creating a backup job](#creating-a-backup-job)
  - [Schedules](#schedules)
  - [Restoring data](#restoring-data)
  - [Telegram delivery](#telegram-delivery)
  - [Storage destinations](#storage-destinations)
  - [Database backups](#database-backups)
- [API](#api)
- [Security](#security)
- [Architecture](#architecture)
- [Testing](#testing)
- [Upgrading](#upgrading)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Features

**Backup engine**
- Unlimited sources per job — any mix of files, directories and databases
- Per-source and per-job exclusion patterns (`*.log`, `.git`, `node_modules`, …)
- TAR, TAR.GZ, ZIP and Zstandard archives with configurable compression levels
- Optional AES-256-GCM encryption of the finished archive
- Post-creation integrity verification (full read-back of every member)
- SHA-256 checksums recorded for every archive
- Streaming implementation — archives are never loaded into RAM
- Cooperative cancellation and automatic cleanup of partial files
- Symlink, permission, ownership and timestamp preservation
- Concurrency limit plus per-job overlap prevention (a job cannot run twice)

**Scheduling**
- Manual, every N minutes, every N hours, daily, weekly, monthly, or custom cron
- Independent timezone per job with DST-aware next-run calculation
- Start/end dates, pause and resume
- Next run time is persisted, so schedules survive restarts

**Recovery**
- Browse the real contents of an archive before restoring
- Full or selective restore by path
- Path traversal and Zip Slip protection
- Optional safety backup of the destination before overwriting
- Live restore progress and per-run history

**Retention**
- Keep last N backups, keep for N days, or both
- Old archives pruned automatically after each successful run
- The newest successful backup is never deleted; running backups are never touched
- Source data is never modified or removed

**Delivery**
- Local disk, SFTP, FTP/FTPS, S3-compatible object storage (AWS S3, MinIO, …)
- Telegram Bot API with automatic archive splitting for large files
- Per-part upload tracking — a partial upload is never reported as success
- Retry with exponential backoff per part
- Encrypted credentials at rest

**Security**
- Argon2id password hashing (bcrypt fallback)
- Server-side sessions with `HttpOnly`, `SameSite=Lax` cookies
- CSRF protection enforced by middleware on every mutating request
- Rate limiting and account lockout after repeated failed logins
- Role-based access control (Administrator / Operator / Viewer)
- Full audit log of authentication, configuration and backup events
- Strict Content-Security-Policy, HSTS, `X-Frame-Options`, `nosniff`
- All SQL through SQLAlchemy parameter binding; no shell invocation anywhere
- Optional TOTP two-factor verification

**Operations**
- Live dashboard: counts, success rate, storage usage, activity charts
- Server monitoring: CPU, memory, disk, I/O, network, uptime, service state
- In-app, Telegram and email notifications with per-event channel control
- Full REST API with OpenAPI documentation
- CSV / JSON export of backup history, log download

**Interface**
- Modern, responsive panel with dark and light themes
- Full RTL support with a Persian interface alongside English
- Custom accent colour, toast notifications, modals, live progress
- Charts rendered by a purpose-built SVG library (no external CDN)
- Every control is wired to a real backend endpoint

---

## Screenshots

Screenshots are **not** included in this repository: they date quickly and risk
leaking hostnames, paths and tokens from whatever instance produced them. Run
the panel and capture your own — [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md)
lists every screen to capture and how to do it safely.

For a written walkthrough of each screen, see [docs/USAGE.md](docs/USAGE.md).

---

## Requirements

| Component | Minimum |
|---|---|
| OS | Ubuntu 22.04 / 24.04, Debian 12+ |
| Python | 3.12 |
| RAM | 512 MB (1 GB recommended) |
| Disk | 1 GB for the application + space for archives |
| Database | SQLite (default) or PostgreSQL 14+ |
| Init system | systemd |
| Web server | Nginx (installed by the installer) |

Optional, for database backups:

| Database | Tool |
|---|---|
| MySQL / MariaDB | `mysqldump` or `mariadb-dump` |
| PostgreSQL | `pg_dump` |
| SQLite | built in (uses SQLite's online backup API) |

---

## Installation

### Automated installer (Ubuntu / Debian)

**One command, straight from GitHub:**

```bash
curl -fsSL https://raw.githubusercontent.com/OfficialMaziar/TokserBackuper/main/install.sh | sudo bash
```

The script downloads the project to a temporary directory, runs the installer,
and cleans up afterwards. Nothing is left behind except the installation itself.

Pass options after `-s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/OfficialMaziar/TokserBackuper/main/install.sh \
  | sudo bash -s -- --domain backup.example.com --http-port 7676
```

**If the repository is private**, pass a token with `repo` scope. It is used
once for the download and is never written to disk:

```bash
TBM_TOKEN=ghp_xxxxxxxx curl -fsSL <installer-url> | sudo -E bash -s --
```

Or download the tarball yourself and run the installer from it:

```bash
curl -fsSL -H "Authorization: Bearer $TBM_TOKEN"   https://api.github.com/repos/OfficialMaziar/TokserBackuper/tarball/main -o tbm.tar.gz
tar -xzf tbm.tar.gz && cd TokserBackuper-* && sudo ./scripts/install.sh
```

Prefer to read the script first:

```bash
curl -fsSL https://raw.githubusercontent.com/OfficialMaziar/TokserBackuper/main/install.sh -o tbm-install.sh
less tbm-install.sh
sudo bash tbm-install.sh
```

Or install from a clone:

```bash
git clone https://github.com/OfficialMaziar/TokserBackuper.git
cd TokserBackuper
sudo ./scripts/install.sh --domain backup.example.com
```

The installer:

1. Verifies the OS version and Python 3.12+
2. Installs system packages (Python, archive tools, database clients)
3. Creates an unprivileged `TBM` system user
4. Copies the application to `/opt/tokser-backup-manager`
5. Creates a virtual environment and installs dependencies
6. Generates `.env` with random secret and encryption keys
7. Initialises the database schema
8. Creates the administrator account (interactively, or defers to `/setup`)
9. Installs and starts the systemd service
10. Configures an Nginx reverse proxy
11. Runs a health check

**Ports.** The installer asks which ports to use when run in a terminal, and
skips a busy default automatically — so it can be installed on a server that
already hosts other sites:

- **Internal port** (default `8000`, bound to `127.0.0.1`): the application itself
- **Public HTTP port** (default `80`): the Nginx vhost facing the internet

If port 80 is already served by another site, the installer publishes on `8080`
(or the port you type) and leaves the existing site's configuration untouched.
The stock Nginx welcome page is only removed when it is still unmodified.

Useful flags:

```bash
sudo ./scripts/install.sh --no-nginx          # application only
sudo ./scripts/install.sh --self-signed       # generate a TLS certificate
sudo ./scripts/install.sh --port 9000         # internal application port
sudo ./scripts/install.sh --http-port 8080    # public Nginx port
sudo ./scripts/install.sh --non-interactive   # unattended (setup at /setup)
```

Re-running the installer upgrades in place and preserves your data, `.env`
and `config.yaml`.

### Docker

```bash
cp .env.example .env
# Set TBM_SECRET_KEY and TBM_ENCRYPTION_KEY:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d
```

The panel listens on `http://127.0.0.1:8080`. Mount the directories you want to
back up read-only under `/sources/...` and reference those paths in your jobs.

### Manual installation

```bash
sudo useradd --system --create-home --home-dir /opt/tokser-backup-manager tokser
sudo git clone https://github.com/OfficialMaziar/TokserBackuper.git /opt/tokser-backup-manager
cd /opt/tokser-backup-manager

sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

sudo cp .env.example .env
sudo sed -i "s|^TBM_SECRET_KEY=.*|TBM_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')|" .env
sudo sed -i "s|^TBM_ENCRYPTION_KEY=.*|TBM_ENCRYPTION_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')|" .env
sudo chmod 600 .env

sudo -u TBM .venv/bin/python -c "from app.main import bootstrap; bootstrap()"
sudo cp systemd/TBM.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now TBM
```

Then open the panel — the first visit redirects to `/setup`.

---

## Command line administration

The installer puts a `tbm` command in `/usr/local/bin`. Everything the panel can
do with accounts, jobs and backups is also available from a terminal — useful
when the panel is unreachable, in scripts, or over SSH.

```bash
tbm status                       # service, job and disk overview
tbm doctor                       # diagnose configuration problems
tbm --json status                # machine-readable output

tbm user list                    # accounts, roles, lockout state
tbm user passwd admin            # change a password (prompts; also clears lockout)
tbm user create ops --role operator
tbm user unlock admin            # clear a failed-login lockout
tbm user role ops admin
tbm user disable ops
tbm user delete ops --yes

tbm job list
tbm job show 3
tbm job run 3                    # start now
tbm job run 3 --wait             # start and wait for the result
tbm job disable 3

tbm backup list --limit 20
tbm backup show 42
tbm backup verify 42             # re-check archive integrity
tbm backup delete 42 --yes

tbm service status | restart | stop | start
tbm service logs -f              # follow the journal

tbm maintenance recalc           # recompute all next-run times
tbm maintenance prune-sessions
tbm maintenance vacuum           # compact SQLite
tbm maintenance check-disk       # exit 1 when disk is low (for monitoring)

tbm access grant /root           # let the service read /root (read-only ACL)
tbm access grant /var/www
tbm access check  /root          # exit 0 when readable
tbm access revoke /root
```

Notes:

- Password changes and other database edits run as the `TBM` user so file
  ownership stays consistent; `service` commands need root and re-run
  themselves under `sudo`.
- Destructive commands (`delete`) require `--yes`.
- The CLI refuses to demote, disable or delete the last administrator.
- Run `tbm <command> --help` for the options of any command.
- The service runs as the unprivileged `TBM` account. To back up `/root` or
  other 0700 directories, use `tbm access grant` rather than running as root.

---

## Configuration

Configuration is layered; later sources win:

1. Built-in defaults (`app/core/config.py`)
2. `config.yaml` (copy from `config.example.yaml`)
3. Environment variables / `.env`

Every setting is documented in [`config.example.yaml`](config.example.yaml) and
[`.env.example`](.env.example). The most important ones:

| Variable | Purpose |
|---|---|
| `TBM_DATABASE_URL` | SQLite or PostgreSQL connection string |
| `TBM_SECRET_KEY` | Token/session signing key — **keep secret** |
| `TBM_ENCRYPTION_KEY` | Key that encrypts stored credentials — **keep secret** |
| `TBM_BACKUP_DIR` | Where archives are written |
| `TBM_MAX_CONCURRENT` | Simultaneous backup jobs |
| `TBM_SECURE_COOKIE` | Set `true` when served over HTTPS |
| `TBM_ALLOWED_HOSTS` | Restrict accepted `Host` headers |

> **Back up your `.env`.** The `TBM_ENCRYPTION_KEY` is required to decrypt the
> storage passwords, bot tokens and encryption passwords stored in the database.
> Without it those secrets are unrecoverable (the backups themselves are
> unaffected — they use their own per-job passwords).

Many runtime values can also be changed from **Settings** in the panel.

---

## First run

1. Open `https://your-host/`.
2. If no account exists you are redirected to `/setup`.
3. Create the administrator: at least 10 characters, containing letters and digits.
4. Sign in. The dashboard loads live data.

No default password is ever created. The setup form validates strength
server-side as well as in the browser.

---

## Usage

### Creating a backup job

1. **Backup Jobs → New Backup Job**
2. Enter a name and optional description.
3. Add sources: click **+ Add**, type an absolute path or use **Browse**. Each
   row shows whether the path exists and is readable by the service user.
4. Optionally add exclusion patterns per source (`*.log, cache, .git`).
5. Choose compression, level, encryption, and a retention policy.
6. Pick a schedule (or leave it manual).
7. **Save**, then **▶** to run immediately.

Progress is visible on the backup detail page, which updates live.

### Schedules

| Type | Behaviour |
|---|---|
| Manual | Only runs when started from the panel or API |
| Every N minutes | Fixed interval from the previous run |
| Every N hours | Interval anchored at a chosen minute |
| Daily | A specific hour and minute each day |
| Weekly | A chosen weekday, hour and minute |
| Monthly | A chosen day of month (clamped to short months), hour and minute |
| Custom cron | Standard 5-field cron, e.g. `0 3 * * mon-fri` |

Timezones are honoured per job, including DST transitions. A job that is still
running is never started a second time — the scheduler logs the skip and waits
for the next window.

### Restoring data

1. **Restore Center**, or open a specific backup and press **Restore**.
2. Inspect the archive contents first.
3. Choose a destination directory (absolute path).
4. Optionally list specific paths to restore (blank restores everything).
5. Decide whether to overwrite existing files and whether to create a safety
   backup of the destination first.
6. Start the restore and watch progress in **Restore history**.

Archives are extracted member by member with path validation; entries that
would escape the destination are skipped and logged.

### Telegram delivery

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Send your bot a message, then get the chat ID (e.g. via `@userinfobot`).
3. **Telegram → Add Telegram Destination**, paste both values.
4. **Test** verifies the token; **Send test** delivers a real message.
5. Enable it on a job with **Upload archive to Telegram**.

Files above 49 MiB are split automatically. Each part is uploaded with retries
and the aggregate result is recorded — an incomplete upload is stored as
`partial`, never as success. Point `TBM_TELEGRAM_API` at a self-hosted
[local Bot API server](https://github.com/tdlib/telegram-bot-api) to raise the
limit to 2 GB.

### Storage destinations

| Type | Notes |
|---|---|
| Local | Any writable directory, including mounted disks |
| SFTP | Password or private-key authentication |
| FTP / FTPS | TLS enabled by default (`tls: true`) |
| S3 / MinIO | Native SigV4 signing; multipart upload above 64 MiB |

Credentials are encrypted with `TBM_ENCRYPTION_KEY` before being stored and are
never returned by the API (only masked values are shown).

### Database backups

Add a database source inside a job and choose MySQL, MariaDB, PostgreSQL or
SQLite. Dumps are written with consistent-snapshot options:

- MySQL/MariaDB — `--single-transaction --quick`, credentials passed through a
  temporary `0600` option file (never on the command line)
- PostgreSQL — `pg_dump` with `PGPASSWORD` in the environment
- SQLite — the online backup API, safe while the database is in use

Passwords never appear in logs.

---

## API

Interactive documentation: `https://your-host/api/docs` (Swagger UI) and
`https://your-host/api/redoc`.

```bash
# Sign in and keep the session cookie
curl -c cookies.txt -X POST https://your-host/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# Read the dashboard
curl -b cookies.txt https://your-host/api/v1/dashboard
```

The login response contains a `csrf_token`. Every mutating request must send it
in the `X-CSRF-Token` header:

```bash
curl -b cookies.txt -X POST https://your-host/api/v1/jobs/1/run \
  -H "X-CSRF-Token: <csrf_token>"
```

Main resource groups: `auth`, `jobs`, `sources`, `backups`, `storage`,
`telegram`, `notifications`, `users`, `logs`, `settings`, `monitoring`.

---

## Security

- Passwords hashed with Argon2id; bcrypt hashes from older versions are accepted
  and transparently re-hashed on login
- Sessions stored server-side; only a SHA-256 hash of the token is persisted
- CSRF enforced by middleware for all cookie-authenticated mutations
- Login rate limiting per IP plus per-account lockout
- RBAC on every endpoint (`jobs:write`, `backups:restore`, …)
- Audit trail of logins, failures, configuration changes and backup operations
- Zip Slip and path traversal blocked during extraction; restore destinations
  must be absolute and existing files are not overwritten without consent
- All subprocess calls use argument lists, never a shell
- Security headers and a restrictive Content-Security-Policy on every response
- The service runs unprivileged; grant read access to specific paths via group
  membership instead of running as root
- Remove `.env`, `data/`, `backups/` and `logs/` from any shared copy

To report a vulnerability, see [SECURITY.md](SECURITY.md).

---

## Architecture

```
tokser-backup-manager/
├── app/
│   ├── main.py                 # FastAPI app, middleware, bootstrap, page routes
│   ├── core/                   # config, database, security, logging
│   ├── models/                 # SQLAlchemy entities
│   ├── schemas/                # Pydantic request/response models
│   ├── api/                    # routers + shared dependencies
│   ├── services/               # backup, archive, restore, cron, retention,
│   │                           # storage backends, telegram, db dump, monitoring
│   ├── templates/              # login, setup, SPA shell
│   └── static/                 # CSS design system, JS modules, icons
├── migrations/                 # Alembic
├── tests/                      # pytest suite + offline runner
├── scripts/                    # install, uninstall, healthcheck
├── systemd/                    # service unit
└── docs/                       # English and Persian documentation
```

**Request flow:** browser → FastAPI router → dependency (session, CSRF, RBAC) →
service layer → SQLAlchemy → database. Background work (backups, restores) runs
in worker threads with their own sessions; the scheduler is a single daemon
thread that polls persisted `next_run_at` values.

**Why no APScheduler?** The scheduling requirement is only "run this job when
`next_run_at` passes". A ~150-line thread with a real cron parser gives exact
control over persistence, timezones and overlap handling, with no extra
dependency and no in-memory-only state.

---

## Testing

```bash
# With pytest (recommended)
pip install pytest
pytest tests/ -v

# Offline environments without pytest
python tests/run_tests.py -v
```

Coverage includes: cron parsing and next-run calculation across all schedule
types and timezones, archive creation/verification/extraction for all four
formats, encryption round-trips, Zip Slip and traversal rejection, cancellation
cleanup, password hashing and TOTP, CSRF enforcement, RBAC, job CRUD, unlimited
sources, backup execution, overlap prevention, retention pruning, restore
round-trips, settings persistence and security headers.

Tests use an isolated temporary database and never touch real data.

---

## Upgrading

```bash
cd /opt/tokser-backup-manager
sudo ./scripts/install.sh    # upgrades in place, preserving data/.env/config.yaml
```

Or manually:

```bash
cd /opt/tokser-backup-manager
sudo -u TBM git pull
sudo -u TBM .venv/bin/pip install -r requirements.txt
sudo -u TBM .venv/bin/alembic upgrade head
sudo systemctl restart TBM
```

Take a database copy before upgrading major versions:

```bash
sudo -u TBM sqlite3 data/tokser.db ".backup '/root/tbm-$(date +%F).db'"
```

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Backup fails with "No files matched" | The path does not exist or the service account cannot read it. Use **Browse** / path validation, then grant read access: `sudo tbm access grant /var/www` |
| "Permission denied" on a source | The `TBM` user lacks read access. Prefer group membership over root |
| Telegram upload says `partial` | Some parts failed. Check the token, chat ID and file size. Increase `TBM_TELEGRAM_RETRIES` |
| Service won't start | `journalctl -u TBM -n 50`. Usually a bad `.env` value or an unwritable directory |
| Login says "Account locked" | Five failed attempts lock the account for 15 minutes (`TBM_LOGIN_LOCKOUT`) |
| Forgot the admin password | `sudo -u TBM .venv/bin/python -c "..."` — see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Charts empty | No data yet. Run a backup; the series fills in from history |
| S3 test fails with 403 | Check the access/secret key, bucket name, region and endpoint |

`./scripts/healthcheck.sh` returns exit code 0 when healthy.

---

## Roadmap

Implemented in this release: all features listed above.

Planned, and clearly marked as such in the interface:

- **Incremental and differential backups** — the `BackupFile` metadata table and
  `backup_mode` field already record per-file size/mtime/checksum, and history
  rows link to a parent. The engine currently performs full backups only; the
  incremental path is not exposed as a working feature.
- **Remote multi-server agents** — the `servers` table registers hosts and the
  local server is created on first boot. Agent transport and authentication are
  not implemented.
- **Two-factor enrollment UI** — TOTP *verification* is implemented and enforced
  when enabled; the enrollment (QR) screen is not yet built.
- **Email notification polish** — SMTP dispatch works; per-event templating is
  basic.

---

## Documentation

| Document | Contents |
|---|---|
| [docs/README.fa.md](docs/README.fa.md) | مستندات کامل فارسی |
| [docs/USAGE.md](docs/USAGE.md) | Screen-by-screen walkthrough |
| [docs/API.md](docs/API.md) | API reference and examples |
| [docs/SECURITY.md](docs/SECURITY.md) | Security model and hardening |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Development setup and architecture |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Detailed diagnostics |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting policy |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.
Run the test suite before opening a pull request. Never commit real backups,
credentials or database files.

---

## License

MIT — see [LICENSE](LICENSE).

---

**Tokser Backup Manager** · Built and maintained by **TokserTeam**
