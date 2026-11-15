# Development guide

## Setup

```bash
git clone https://github.com/OfficialMaziar/TokserBackuper.git
cd TokserBackuper

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # TBM_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # TBM_ENCRYPTION_KEY

uvicorn app.main:app --reload --port 8000
```

`--reload` restarts on Python changes; static assets are served fresh on every
request, so only a browser refresh is needed for CSS/JS.

The database schema is created automatically on first boot. To work with
migrations instead:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe the change"
```

---

## Layer boundaries

```
HTTP  →  app/api/*.py        routers, validation, permission checks
        app/api/deps.py      session resolution, CSRF, rate limiting
     ↓
Logic →  app/services/*.py   no FastAPI imports here
     ↓
Data  →  app/models/         SQLAlchemy entities
        app/core/database.py engine, session factories
```

Rules:

- Services never import from `app.api`
- Routers contain no business logic beyond request → service mapping
- Anything that touches the filesystem lives in `app/services/`
- Background work opens its own session via `session_scope()`; never reuse a
  request-scoped session in a thread

---

## Adding a feature

### New API endpoint

1. Define request/response models in `app/schemas/__init__.py`.
2. Add the route to the relevant router with:
   - a `require_permission(...)` dependency,
   - a Pydantic body model,
   - an activity log entry for mutations.
3. CSRF is enforced automatically by middleware — nothing to add.
4. Write a test in `tests/test_api.py`.

### New backup source type

1. Add a model or extend `BackupSource`.
2. Handle it in `backup_engine._run_job` where sources are collected.
3. Extend the job form in `app/static/js/views-jobs.js`.
4. Add tests for the happy path and the failure path.

### New storage backend

1. Subclass `BaseBackend` in `app/services/storage_backends.py`, implementing
   `test`, `upload`, `download`, `delete`, `exists`.
2. Register it in `build_backend`.
3. Add the UI form branch in `openStorageModal` (`views-system.js`).
4. Raise `StorageError` with a human-readable message on failure — never let a
   provider exception escape untyped.

### New notification channel

1. Add the channel columns to `NotificationSetting` if needed (migration).
2. Implement the dispatch in `app/services/notifications.py`.
3. Add the toggle column in `views-system.js`.

---

## Frontend structure

| File | Contents |
|---|---|
| `core.js` | API client (`api()`), i18n (`t()`), formatting (`fmt`), toasts, modals, theming, polling |
| `charts.js` | SVG line/bar/donut renderers with tooltips and data tables |
| `views.js` | `Views` registry and `registerViews()` |
| `views-*.js` | One file per view group; each registers an `async function(el, params)` |
| `app.js` | Router, sidebar, topbar actions, boot sequence |

A view is `async function (el, params)` that renders into `el`. Use `poll(name,
fn, ms)` for live updates — polls are cleared automatically on navigation.

**Adding a page:** add a route to `ROUTES`, a nav entry to `NAV` (with a `data-i18n`
key), and a view function in one of the `views-*.js` files. Both `en` and `fa`
strings must be added to `I18N`.

**Charts:** always pass a legend for two or more series, keep one y-axis, and
call `Charts.attachTableToggle(container, button)` so the data table remains
reachable.

---

## Testing

```bash
pytest tests/ -v                    # recommended
python tests/run_tests.py -v        # offline fallback (no pytest needed)
python tests/run_tests.py -k archive
```

`tests/conftest.py` sets isolated environment variables *before* importing the
app, so tests never touch a real database or backup directory. A test that
writes outside `tmp_path` is a bug.

Test categories:

| File | Covers |
|---|---|
| `test_cron.py` | Cron parsing, all schedule types, timezones, edge dates |
| `test_archive.py` | Four formats, encryption, verification, extraction, Zip Slip, cancellation |
| `test_security.py` | Hashing, secret encryption, path safety, TOTP |
| `test_api.py` | Auth, CSRF, RBAC, jobs, backups, restore, retention, settings |

---

## Conventions

- `from __future__ import annotations` at the top of every module
- Type hints on public functions
- Log through `get_logger(__name__)`; never `print`
- Never log secrets — the `RedactFilter` is a safety net, not a licence
- Raise specific exceptions (`BackupError`, `StorageError`, `ArchiveError`)
  and translate them to HTTP status codes in the router
- Timezone-aware datetimes only; use `app.utils.utcnow()`
- Escape every dynamic value in frontend templates with `fmt.escape`

---

## Debugging

```bash
# Structured logs
tail -f logs/tokser.log
tail -f logs/error.log

# Live API exploration
open http://127.0.0.1:8000/api/docs

# Run the scheduler more aggressively while testing
TBM_SCHEDULER_TICK=2 uvicorn app.main:app --reload
```

Set `TBM_DEBUG=true` for verbose logging and uvicorn's reloader.

To exercise a backup without waiting, create a job with a small directory and
press **Run now**; the detail page updates every three seconds while running.

---

## Release checklist

- [ ] `pytest tests/` passes
- [ ] `python -m compileall -q app tests` is clean
- [ ] `bash -n scripts/*.sh` is clean
- [ ] No secrets, `.env`, `data/` or archives staged for commit
- [ ] `CHANGELOG.md` updated
- [ ] `README.md` reflects new configuration options
- [ ] Migration added for any schema change
- [ ] Version bumped in `app/core/config.py`
