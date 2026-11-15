# Troubleshooting

Start with the health check and the service journal:

```bash
./scripts/healthcheck.sh
sudo systemctl status TBM
sudo journalctl -u TBM -n 100 --no-pager
sudo tail -n 100 /opt/tokser-backup-manager/logs/error.log
```

---

## Installation

**"This installer must run as root"**
Run with `sudo`.

**"Port 8000 is already in use"**
Something else is listening. Find it:

```bash
sudo ss -ltnp | grep ':8000'
```

Then either stop it or install on another port: `sudo ./scripts/install.sh --port 9000`.

**"python3-venv" errors**
The installer installs it, but on a minimal image you may need:

```bash
sudo apt-get install -y python3-venv python3-dev build-essential
```

**Health check fails at the end**
The service started but never answered. Check the journal for a traceback. The
usual causes are an unreadable `.env`, a directory the `TBM` user cannot
write to, or a malformed `TBM_DATABASE_URL`.

---

## Service and startup

**Service restart loops**

```bash
sudo journalctl -u TBM -n 200 --no-pager | tail -50
```

Common causes:

| Message | Fix |
|---|---|
| `PermissionError: [Errno 13]` on `data/` or `logs/` | `sudo chown -R tokser:tokser /opt/tokser-backup-manager/{data,logs}` |
| `sqlalchemy.exc.OperationalError: unable to open database file` | Parent directory missing or not writable — create it and chown |
| `Address already in use` | Another process holds the port |
| `pydantic.ValidationError` on startup | An invalid value in `.env`; check the named field |

**Changes to CSS/JS do not appear**
Hard-refresh (Ctrl+Shift+R). Static files are served with a 7-day cache header
through Nginx.

**Panel loads but the API returns 502**
Nginx is up but the application is not. Check the service status and the port
in the Nginx config matches `TBM_PORT`.

---

## Authentication

**"Account temporarily locked"**
Five failed attempts (default) lock the account for 15 minutes. Wait, or clear
it directly:

```bash
sudo -u TBM /opt/tokser-backup-manager/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "/opt/tokser-backup-manager")
from app.core.database import SessionLocal
from sqlalchemy import select
from app.models import User
db = SessionLocal()
u = db.scalar(select(User).where(User.username == "admin"))
u.failed_attempts = 0
u.locked_until = None
db.commit()
print("unlocked")
PY
```

**Forgot the administrator password**

```bash
sudo -u TBM /opt/tokser-backup-manager/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "/opt/tokser-backup-manager")
from app.core.database import SessionLocal
from sqlalchemy import select
from app.core.security import hash_password
from app.models import User, SessionToken
db = SessionLocal()
u = db.scalar(select(User).where(User.username == "admin"))
u.password_hash = hash_password("NewStrongPass123")
u.must_change_password = True
for s in db.scalars(select(SessionToken).where(SessionToken.user_id == u.id)):
    db.delete(s)
db.commit()
print("password reset")
PY
```

**"Setup already completed" but I cannot sign in**
An account exists. Use the reset procedure above.

**Everyone is logged out after a restart**
Sessions are stored in the database, so they normally survive. They do not
survive if `TBM_SECRET_KEY` changed (it does not affect sessions directly, but
changing the data directory does), or if the session TTL elapsed.

---

## Backups

**"No files matched the selected sources"**
The path is missing or unreadable.

```bash
sudo -u TBM test -r /var/www && echo readable || echo "not readable"
sudo -u TBM ls /var/www
```

Grant access through a group rather than root:

```bash
sudo tbm access grant /var/www
sudo tbm service restart
```

For `/root` specifically:

```bash
sudo tbm access check /root     # reports whether it is readable
sudo tbm access grant /root
```

**Backup hangs at "scanning"**
A very large tree or a slow network mount. The scan is time-unbounded by design
(so nothing is silently skipped). Check for a mount that is not responding:

```bash
mount | grep -i nfs
```

**"Not enough free disk space"**
The engine refuses to start below `TBM_MIN_FREE_MB` (default 512 MB). Free space
or lower the threshold. Retention runs after every successful backup, so
lowering `retention_keep_last` will recover space on the next run.

**Archive verification fails**
The archive was truncated — usually a full disk mid-write. The run is marked
failed and the partial file removed. Free space and re-run.

**A job will not start: "Job is already running"**
A previous run is still active. Check its state on the backup detail page. If it
is stuck, restart the service — the thread pool is recreated and the job becomes
available again.

**Database backup fails**
The dump tool is missing or credentials are wrong:

```bash
which mysqldump pg_dump
```

The error message includes the tool's stderr (with passwords redacted).

---

## Restore

**"Refusing to overwrite"**
The destination already contains the files. Either enable **Overwrite existing
files** or restore into an empty directory.

**"Wrong password or corrupted archive"**
The encryption password does not match. The password is stored with the job; if
the job's password was changed after the backup, the old archive cannot be
restored. Provide the original password.

**Some files were skipped**
Those members failed the path-safety check (absolute paths, `..`, or links
escaping the destination). They are listed in the service log:

```bash
sudo grep "Blocked unsafe" /opt/tokser-backup-manager/logs/tokser.log | tail
```

---

## Telegram

**"Bot token is not configured" / "Chat ID is not configured"**
Fill both fields on the destination and ensure it is enabled.

**Test passes but uploads fail**
`getMe` only validates the token. Uploads need the bot to have permission to
post in that chat. For groups, add the bot as a member and use the negative chat
ID.

**Status is `partial`**
Some parts failed. The part count and errors are in the service log. Common
causes: file too large for the configured Bot API server, network timeouts, or
rate limiting. Increase `TBM_TELEGRAM_RETRIES` or point `TBM_TELEGRAM_API` at a
local Bot API server.

**Nothing sent even though a destination is configured**
Check that the job has `telegram_upload_enabled` and a `telegram_destination_id`,
and that the destination has `upload_enabled`.

---

## Storage

**SFTP "Authentication failed"**
Check the username, password or key path, and that the remote directory exists
and is writable.

**FTP tests pass but uploads fail in passive mode**
Some firewalls block the passive data ports. Try toggling `passive` in the
destination config, or use SFTP instead.

**S3 returns 403 SignatureDoesNotMatch**
The secret key is wrong or the endpoint/region do not match the provider. For
MinIO the region is often required even though it is arbitrary.

**S3 returns 400 on multipart**
Some S3-compatible servers reject certain part sizes. The uploader uses 32 MiB
parts, which is compatible with AWS, MinIO and Backblaze B2.

**Credentials show as empty after restoring a database**
`TBM_ENCRYPTION_KEY` changed. Restore the original key from your `.env` backup;
without it the encrypted values cannot be decrypted and must be re-entered.

---

## Scheduling

**A scheduled job never runs**
- Is the job enabled? (`enabled` and the schedule not paused)
- Is `next_run_at` in the future and the scheduler running? Check **Server
  Monitoring** → Scheduler.
- Is `TBM_SCHEDULER=true`?
- Look for `Scheduled job N skipped` in the log — this means the previous run was
  still active.

Recompute all next-run times:

```bash
sudo -u TBM /opt/tokser-backup-manager/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "/opt/tokser-backup-manager")
from app.services.scheduler import recalculate_all
print("jobs updated:", recalculate_all())
PY
```

**Times are off by hours**
Set the job's timezone explicitly. `UTC` is the default; for Iran use
`Asia/Tehran`.

---

## Notifications

**No Telegram notifications, but backups work**
Notification delivery is independent of job success. Check the event is enabled
with the Telegram channel toggled on in **Notifications**, and that a Telegram
destination has `send_notifications` enabled.

**Email never arrives**
SMTP is not configured by default. Fill in the SMTP block in **Settings** and
use **Test email**. Failures are logged to `logs/tokser.log`; the dispatcher
never raises, so a broken SMTP server does not fail backups.

---

## Performance

**High memory during backup**
The engine streams, so memory should stay flat. A spike usually means an
exclusion pattern is matching nothing and a huge tree is being enumerated. Verify
exclusions with a small test job first.

**Backups are slow**
Compression level dominates. `tar.gz` at level 6 is a good balance; level 9 can
be 2–3× slower for a few percent smaller. Zstandard is much faster at similar
ratios — try `zst` with level 6.

**Too many concurrent jobs**
Lower `TBM_MAX_CONCURRENT` (default 2). Concurrent jobs compete for disk I/O.

---

## Database

**Migrating from SQLite to PostgreSQL**

```bash
sudo systemctl stop TBM
sudo -u TBM sqlite3 data/tokser.db ".dump" > /tmp/dump.sql
# Create the PostgreSQL database and user, then:
sudo -u TBM /opt/tokser-backup-manager/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "/opt/tokser-backup-manager")
from app.core.database import Base, engine
from app import models
Base.metadata.create_all(engine)
print("schema created")
PY
```

Then import the data with `pgloader` or by replaying the SQL with the dialect
differences handled. Set `TBM_DATABASE_URL` and restart. Always back up the
SQLite file first.

**"database is locked" (SQLite)**
WAL mode and a 30-second busy timeout are set, which handles normal contention.
Persistent locking means a long-running transaction; usually a huge restore.
Consider PostgreSQL for heavy workloads.

---

## Getting help

Collect the following before opening an issue:

```bash
tokser-backup-manager --version 2>/dev/null || grep APP_VERSION /opt/tokser-backup-manager/app/core/config.py
sudo journalctl -u TBM -n 200 --no-pager
./scripts/healthcheck.sh
cat /etc/os-release | head -3
```

Remove all credentials, tokens and personal data from anything you paste.
