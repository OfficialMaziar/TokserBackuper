# Usage guide

A walkthrough of every screen in Tokser Backup Manager, in the order you would
normally use them.

---

## 1. Sign in

`/login`

Enter the administrator credentials created during installation. Five failed
attempts lock the account for 15 minutes (configurable). A successful sign-in
returns a session cookie and a CSRF token; the panel keeps the token and sends
it with every state-changing request.

The login page has a language toggle in the footer and detects whether setup
has been completed, redirecting to `/setup` when no account exists.

## 2. Dashboard

`/`

Eight live tiles:

| Tile | Meaning |
|---|---|
| Total Backup Jobs | All jobs, with how many are enabled |
| Successful Backups | Lifetime successes and the overall success rate |
| Failed Backups | Lifetime failures and the number currently running |
| Total Backup Size | Sum of successful archive sizes, plus free disk space |
| Last Backup | When the most recent successful backup finished |
| Next Scheduled Backup | The nearest upcoming run across all jobs |
| Server Uptime | Host uptime and hostname |
| Available Disk Space | Free and total on the backup volume |

Below the tiles:

- **Backup Activity** — successful versus failed runs per day for 14 days
- **Backup Storage Usage** — ring chart of used versus free on the backup volume
- **Backup Size History** — area chart of bytes produced per day
- **System Health** — CPU, memory and disk bars with a link to full monitoring
- **Recent Activity** — the latest eight runs, click-through to details

Every chart has a **Show data table** toggle for screen readers, colour-blind
users and anyone who wants exact numbers. The dashboard polls every 15 seconds.

## 3. Backup Jobs

`/jobs`

A searchable, filterable table of every job with its schedule description,
state, last run, next run and success ratio.

Row actions:

| Icon | Action |
|---|---|
| ▶ | Run now (disabled while the job is running) |
| ⏸ / ⏵ | Toggle enabled state |
| ✎ | Edit |
| ⧉ | Duplicate (created disabled, schedule paused) |
| 🗑 | Delete, with confirmation |

Deleting a job removes its history records; archive files already on disk are
left alone.

## 4. Create / edit a backup job

`/jobs/new`, `/jobs/{id}/edit`

The form is split into sections.

**General** — name (must be unique) and description.

**Sources** — add any number of rows. Each row has a name, an absolute path, an
optional exclusion list and an enabled flag. The path is validated as you type:

- *Path does not exist* — the directory or file is missing
- *Permission denied* — it exists but the service user cannot read it
- *Readable · 1.2 GB · directory* — ready to back up

**Browse** opens a directory picker that walks the filesystem from `/`.

**Database sources** — MySQL, MariaDB, PostgreSQL or SQLite. Each row takes the
connection details; for SQLite supply a file path instead of host/port.

**Schedule** — pick a type; the relevant fields appear beneath. Cron accepts
standard five-field syntax with names (`0 3 * * mon-fri`). Timezone defaults to
UTC. A paused schedule computes no next run.

**Archive** — compression format and level, global exclude patterns, and whether
to follow symlinks and preserve permissions.

**Destination and retention** — local backup directory or a configured storage
destination, an optional Telegram destination with an upload toggle, and the
retention policy. Leave *Keep for N days* blank for unlimited age.

**Encryption** — AES-256-GCM with your password. **The password cannot be
recovered**; without it the archive cannot be verified or restored. Leave the
field blank when editing to keep the existing password.

Saving returns to the job list.

## 5. Backup Sources

`/sources`

A read-only cross-job view of every configured source: name, path, owning job,
estimated size, enabled state and exclusion patterns. Sources are edited inside
their job.

## 6. Backup History

`/backups`

Filterable by text, status and date range, paginated 50 per page. The status
column distinguishes `success`, `failed`, `running`, `pending`, `cancelled` and
`partial`.

**CSV** and **JSON** export the most recent 10,000 records. A running backup
offers a **Cancel** action.

## 7. Backup details

`/backups/{id}`

- Status, error message and a live progress bar while running
- **Summary**: trigger, mode, timings, archive name and format, sizes,
  compression ratio, file count, verification state, storage path and Telegram
  delivery result
- **Archive contents**: the real entries read from the archive file, or the
  recorded per-file metadata via the toggle
- Actions: **Verify archive**, **Download**, **Restore**, **Cancel**, **Delete**

Verification reads every member to EOF and updates the stored verification flag.

## 8. Restore Center

`/restore`

1. Choose a backup from the dropdown — its contents are previewed.
2. Enter an absolute destination path.
3. Optionally list specific archive paths, one per line. Blank restores all.
4. Choose whether to overwrite existing files and whether to create a safety
   backup of the destination first.
5. Confirm and start.

The restore runs in the background. Progress and the result appear under
**Restore history**. Entries that would escape the destination are skipped and
logged; existing files are never replaced without the overwrite checkbox.

## 9. Schedules

`/schedules`

Two tables: jobs with a real schedule (showing timezone, next run, state, with
pause/resume/run actions) and manual-only jobs.

## 10. Storage

`/storage`

Add and manage destinations. Supported types:

| Type | Fields |
|---|---|
| Local | directory path |
| SFTP | host, port, username, password or private key, remote path |
| FTP | host, port, username, password, remote path, FTPS toggle |
| S3 / MinIO | endpoint, region, bucket, prefix, access key, secret key |

**Test** verifies connectivity before saving (unsaved) or against the stored
configuration. Secrets are encrypted and never returned by the API. A
destination in use by a job cannot be deleted.

## 11. Telegram

`/telegram`

Create a bot with @BotFather, capture its token, then find your chat ID. Each
destination stores a token, chat ID and three switches: enabled, send
notifications, allow uploads.

- **Test** calls `getMe` and reports the bot username
- **Send test** delivers a real message
- **Edit** leaves the token field blank to keep the existing one

During a backup, archives over 49 MiB are split; each part is uploaded with
retries and the result is stored as `sent`, `partial` or `failed`.

## 12. Notifications

`/notifications`

A matrix of eight events against four columns: enabled, in-app, Telegram and
email. Changes save immediately. The **Test delivery** buttons exercise each
channel.

Events: backup started, completed, failed, restore completed, low disk space,
storage connection failed, scheduler error, security alert.

## 13. Server Monitoring

`/monitoring`

Refreshes every eight seconds. Top tiles show CPU, memory, disk and uptime;
panels show CPU/memory/swap bars, backup volume usage, network throughput, disk
I/O, hostname, platform, Python version, load average, scheduler state, backup
service concurrency and the last scheduler tick.

## 14. Activity Logs

`/logs`

Every audited action with timestamp, user, action code, detail, IP and level.
Search by text and filter by level. **Download log** returns the rotating
application log file.

## 15. Users and Roles

`/users` (administrators only)

| Role | Can |
|---|---|
| Administrator | Everything, including users, settings, storage and Telegram |
| Operator | Create and run jobs, restore, manage sources and destinations |
| Viewer | Read-only access to dashboards, history and monitoring |

Create users with a temporary password; they are forced to change it at first
login. **Reset password** issues a new temporary password and revokes all their
sessions. The last administrator cannot be deleted, and you cannot demote or
disable your own account.

## 16. Security

`/security`

Change your password (requires the current one; all other sessions are revoked).
Review active sessions with IP, device, creation and expiry, and revoke any of
them.

## 17. Settings

`/settings`

Appearance (title, default language and theme), backup engine limits (minimum
free disk, concurrency, verification) and SMTP configuration for email
notifications. Includes an **Environment** panel showing version, vendor,
environment, database backend and the backup directory path.

## 18. API documentation

`/api-docs`

Links to Swagger UI and ReDoc, a `curl` example of the login/CSRF flow, and a
table of the main endpoints.

## 19. About

`/about`

Version, vendor, runtime, database, backup disk usage, the implemented feature
list and the honest roadmap of what is not yet shipped.

---

## Common workflows

**Nightly website backup to Telegram**
1. New job, name *Website Backup*.
2. Source `/var/www`, exclude `*.log, cache, node_modules`.
3. Compression `tar.gz` level 6, keep last 14.
4. Schedule daily at 03:00, timezone `Asia/Tehran`.
5. Telegram destination attached, upload enabled.
6. Save and run once to confirm delivery.

**Database plus configuration, weekly**
1. New job, name *DB and Config*.
2. Source `/etc/nginx`, `/etc/apache2`.
3. Add a database source for `shop` (MySQL).
4. Schedule weekly, Monday 02:00.
5. Retention: keep 8.
6. Encrypt the archive with a password stored in your password manager.

**Disaster recovery drill**
1. Open **Restore Center** and select the most recent successful backup.
2. Preview the contents to confirm the expected paths exist.
3. Restore to a scratch directory such as `/srv/restore-test` with the safety
   backup enabled.
4. Verify the restored tree, then remove the scratch directory.
