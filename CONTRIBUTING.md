# Contributing to Tokser Backup Manager

Thank you for helping improve TBM.

## Getting started

```bash
git clone https://github.com/OfficialMaziar/TokserBackuper.git
cd TokserBackuper

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then set TBM_SECRET_KEY / TBM_ENCRYPTION_KEY
uvicorn app.main:app --reload
```

The panel is at <http://127.0.0.1:8000>. The first visit redirects to `/setup`.

## Project layout

| Path | Responsibility |
|---|---|
| `app/core/` | configuration, database engine, security primitives, logging |
| `app/models/` | SQLAlchemy entities (single module, grouped by concern) |
| `app/schemas/` | Pydantic validation models |
| `app/api/` | FastAPI routers; `deps.py` holds shared auth/CSRF/permission dependencies |
| `app/services/` | business logic — no FastAPI imports here |
| `app/static/js/` | one file per view group; `core.js` holds the API client, i18n and UI primitives |
| `tests/` | pytest suite |

## Coding guidelines

- **Python 3.12+**, type hints on public functions, `from __future__ import annotations`
- Services must not import from `app.api`; API layers may import services
- Never build SQL by string concatenation
- Never call a shell; use `subprocess.run([...])` with an argument list
- New endpoints require: authentication, a permission check, CSRF protection
  (automatic via middleware) and a Pydantic request model
- Log meaningful events; never log passwords, tokens or decrypted secrets
- User-facing strings belong in the i18n dictionary in `core.js` with both
  `en` and `fa` entries
- No CDN dependencies in the frontend — the panel must work on an isolated server

## Tests

Every behavioural change needs a test.

```bash
pytest tests/ -v                   # preferred
python tests/run_tests.py -v       # offline fallback
```

Requirements for a pull request:

1. The full suite passes
2. New behaviour is covered
3. No new security warnings
4. Tests never depend on the developer's real data directories

## Commit messages

Use the conventional form:

```
feat(backup): support per-source exclusion patterns
fix(restore): reject absolute paths in selected members
docs(readme): document S3 endpoint configuration
test(cron): cover DST transitions
```

## Pull requests

- Keep changes focused; separate refactors from features
- Describe the problem and the approach, not just the diff
- Note any migration or configuration change
- Include screenshots for interface changes
- Link the related issue

## Security issues

Do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## What not to commit

`.env`, `config.yaml`, anything in `data/`, `backups/` or `logs/`, real backup
archives, database files, keys, or credentials of any kind. `.gitignore` covers
these — if you find a gap, fix the ignore rule in the same PR.
