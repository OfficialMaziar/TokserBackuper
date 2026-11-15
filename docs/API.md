# API reference

Base path: `/api/v1` · OpenAPI: `/api/openapi.json` · Swagger UI: `/api/docs` ·
ReDoc: `/api/redoc`

## Authentication

Sessions are cookie-based. Sign in, keep the cookie, and send the returned
`csrf_token` in `X-CSRF-Token` on every mutating request.

```bash
# 1. Sign in (stores the session cookie)
curl -c cookies.txt -X POST https://your-host/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
# → {"ok": true, "user": {...}, "csrf_token": "..."}

# 2. Send the token on mutations
curl -b cookies.txt -X POST https://your-host/api/v1/jobs/1/run \
  -H "X-CSRF-Token: <csrf_token>"
```

Alternatively, send the session token as `Authorization: Bearer <token>`;
bearer requests are exempt from CSRF.

| Status | Meaning |
|---|---|
| 200 | Success |
| 400 | Invalid request (e.g. job has no sources) |
| 401 | Not authenticated |
| 403 | Missing permission, or invalid/missing CSRF token |
| 404 | Resource not found |
| 409 | Conflict (duplicate name, job already running, in use) |
| 422 | Validation error (field-level details in `detail`) |
| 429 | Rate limit exceeded |

Errors are JSON: `{"detail": "human readable message"}`. Validation errors use
FastAPI's list form with a `loc` path and `msg` per field.

---

## Auth

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | `/auth/status` | — | Setup state and current session |
| POST | `/auth/setup` | — | Create the first administrator (once only) |
| POST | `/auth/login` | — | Sign in |
| POST | `/auth/logout` | session | End the session |
| GET | `/auth/me` | session | Current user, permissions, CSRF token |
| POST | `/auth/change-password` | session | Change own password |
| GET | `/auth/sessions` | session | List own sessions |
| DELETE | `/auth/sessions/{id}` | session | Revoke one session |

```bash
curl -b cookies.txt https://your-host/api/v1/auth/me
```

---

## Jobs

| Method | Path | Permission |
|---|---|---|
| GET | `/jobs?q=&enabled=` | `jobs:read` |
| POST | `/jobs` | `jobs:write` |
| GET | `/jobs/{id}` | `jobs:read` |
| PUT | `/jobs/{id}` | `jobs:write` |
| DELETE | `/jobs/{id}` | `jobs:write` |
| POST | `/jobs/{id}/duplicate` | `jobs:write` |
| POST | `/jobs/{id}/run` | `jobs:run` |
| POST | `/jobs/{id}/pause` | `jobs:write` |
| POST | `/jobs/{id}/resume` | `jobs:write` |
| POST | `/jobs/{id}/toggle` | `jobs:write` |

```bash
curl -b cookies.txt -X POST https://your-host/api/v1/jobs \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{
    "name": "Website Backup",
    "compression": "tar.gz",
    "compression_level": 6,
    "sources": [
      {"name": "www", "path": "/var/www", "enabled": true,
       "exclude_patterns": ["*.log", "cache"]}
    ],
    "schedule": {"schedule_type": "daily", "hour": 3, "minute": 0,
                 "timezone": "Asia/Tehran"},
    "retention_keep_last": 14
  }'
```

`POST /jobs/{id}/run` returns `{"ok": true, "backup_id": 42}`; poll
`GET /backups/42` for status and progress. A second run while one is active
returns **409**.

### Sources

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | `/sources/browse?path=/var/www` | `sources:read` | List a directory |
| POST | `/sources/validate` | `sources:read` | Existence, readability, size |
| POST | `/sources/estimate` | `sources:read` | Size estimate (time-boxed) |

---

## Backups

| Method | Path | Permission |
|---|---|---|
| GET | `/backups?job_id=&status=&q=&date_from=&date_to=&limit=&offset=` | `backups:read` |
| GET | `/backups/export?format=csv\|json` | `backups:read` |
| GET | `/backups/{id}` | `backups:read` |
| GET | `/backups/{id}/files?q=` | `backups:read` |
| GET | `/backups/{id}/archive` | `backups:read` |
| POST | `/backups/{id}/verify` | `backups:read` |
| GET | `/backups/{id}/download` | `backups:read` |
| POST | `/backups/{id}/cancel` | `backups:write` |
| DELETE | `/backups/{id}` | `backups:delete` |
| POST | `/backups/{id}/restore` | `backups:restore` |
| GET | `/restores` | `backups:read` |
| GET | `/restores/{id}` | `backups:read` |

`GET /backups/{id}/files` reads recorded metadata; `/archive` reads the actual
archive from disk (requires the password for encrypted archives and returns it
from the stored configuration).

```bash
curl -b cookies.txt -X POST https://your-host/api/v1/backups/42/restore \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{
    "destination": "/srv/restore",
    "selected_paths": ["var/www/index.php"],
    "overwrite": false,
    "create_safety_backup": true,
    "preserve_permissions": true
  }'
# → {"ok": true, "restore_id": 7}
```

`selected_paths` must be archive-relative and may not contain `..` or start
with `/`; violations return **422**.

---

## Storage

| Method | Path | Permission |
|---|---|---|
| GET | `/storage` | `storage:read` |
| POST | `/storage` | `storage:write` |
| PUT | `/storage/{id}` | `storage:write` |
| DELETE | `/storage/{id}` | `storage:write` |
| POST | `/storage/{id}/test` | `storage:read` |
| POST | `/storage/test-unsaved` | `storage:read` |

```bash
curl -b cookies.txt -X POST https://your-host/api/v1/storage \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{
    "name": "Offsite S3",
    "storage_type": "s3",
    "config": {"endpoint": "https://s3.example.com", "region": "us-east-1",
               "bucket": "backups", "prefix": "tokser", "access_key": "AKIA..."},
    "secrets": {"secret_key": "..."}
  }'
```

Secrets are encrypted at rest and never returned — responses include
`has_secrets` instead.

---

## Telegram

| Method | Path | Permission |
|---|---|---|
| GET | `/telegram` | `telegram:read` |
| POST | `/telegram` | `telegram:write` |
| PUT | `/telegram/{id}` | `telegram:write` |
| DELETE | `/telegram/{id}` | `telegram:write` |
| POST | `/telegram/{id}/test` | `telegram:read` |
| POST | `/telegram/{id}/send-test` | `telegram:read` |
| POST | `/telegram/test-unsaved` | `telegram:read` |

Token values are returned masked (`bot_token_masked`).

---

## Notifications

| Method | Path | Permission |
|---|---|---|
| GET | `/notifications` | session |
| POST | `/notifications/{id}/read` | session |
| POST | `/notifications/read-all` | session |
| GET | `/notifications/settings` | `notifications:read` |
| PUT | `/notifications/settings` | admin |
| POST | `/notifications/test` | admin |

---

## Users

| Method | Path | Permission |
|---|---|---|
| GET | `/users` | admin |
| GET | `/users/roles` | admin |
| POST | `/users` | admin |
| PUT | `/users/{id}` | admin |
| POST | `/users/{id}/reset-password` | admin |
| DELETE | `/users/{id}` | admin |

---

## Dashboard, monitoring, settings

| Method | Path | Permission |
|---|---|---|
| GET | `/dashboard` | `dashboard:read` |
| GET | `/monitoring` | `monitoring:read` |
| GET | `/health` | — |
| GET | `/about` | — |
| GET | `/settings` | session |
| PUT | `/settings` | admin |
| GET | `/logs?q=&level=&action=&limit=&offset=` | `logs:read` |
| GET | `/logs/download` | `logs:read` |

`/health` returns `{"status": "ok", "database": "ok", "scheduler": {...}}` and
is safe to poll from monitoring systems — it requires no authentication and
exposes no sensitive data.

---

## Dashboard response shape

```json
{
  "stats": {
    "total_jobs": 4, "enabled_jobs": 3,
    "successful_backups": 128, "failed_backups": 2,
    "running_backups": 0, "pending_backups": 0, "total_backups": 130,
    "total_backup_size": 48231004160, "backup_success_rate": 98.5,
    "backups_last_24h": 4, "unread_notifications": 1
  },
  "last_backup": {"id": 128, "job_name": "Website", "finished_at": "...", "archive_size": 834125},
  "next_backup": {"job_id": 2, "job_name": "Database", "next_run_at": "..."},
  "disk": {"path": "/var/backups/tokser", "total": 0, "used": 0, "free": 0, "percent": 12.4, "level": "ok"},
  "system": {"cpu_percent": 3.2, "memory_percent": 41.7, "...": "..."},
  "activity_series": [{"date": "2026-11-01", "success": 4, "failed": 0, "size": 91234}],
  "recent_backups": [],
  "scheduler": {"enabled": true, "running": true, "last_tick": "...", "tick_seconds": 15}
}
```
