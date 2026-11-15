# Screenshots

The panel is best seen live. This page describes what each screen contains so
you can follow along, and explains how to capture your own screenshots.

## Capturing screenshots

Screenshots are not committed to the repository (they would age badly and can
leak data from whatever instance produced them). Generate them from your own
installation:

```bash
# 1. Start the application against a demo dataset
export TBM_DATA_DIR=./data-demo TBM_BACKUP_DIR=./backups-demo
export TBM_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export TBM_ENCRYPTION_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
uvicorn app.main:app --port 8000

# 2. Sign in at http://127.0.0.1:8000 and complete setup

# 3. Capture with any screenshot tool, e.g.
#    Firefox: right-click → Take Screenshot
#    Chrome:  DevTools → Cmd/Ctrl+Shift+P → "Capture full size screenshot"
```

Use a throwaway instance. Never capture screens with real hostnames, paths,
tokens or backup contents visible.

## Screens to capture

| Screen | What it shows |
|---|---|
| **Login** | Centred card, brand mark, gradient background, language toggle |
| **Setup** | Administrator creation with password-strength guidance |
| **Dashboard** | Eight stat tiles, activity bar chart, storage ring, size area chart, health bars, recent table |
| **Backup Jobs** | Searchable table with schedule description, state badges and row actions |
| **Create job — sources** | Source rows with live path validation, browse picker, exclusion patterns |
| **Create job — schedule** | Schedule type selector with the matching dynamic fields |
| **Backup detail** | Summary definition list, archive content browser, action bar |
| **Restore Center** | Backup selector, content preview, destination form, restore history |
| **Storage** | Destination table with connection test status |
| **Telegram** | Destination table with masked tokens and test actions |
| **Notifications** | Event × channel switch matrix |
| **Server Monitoring** | CPU/memory gauges, disk and network panel, system information |
| **Activity Logs** | Filterable audit table |
| **Users** | User table with roles and 2FA state |
| **Settings** | Appearance, engine and SMTP sections with an environment panel |
| **Dark / light** | The same dashboard in both themes |
| **Persian / RTL** | The dashboard with the interface in Persian |

## Image guidance

- Capture at 1440×900 or wider; the layout is designed for desktop
- Use the dark theme for the README hero image, light for documentation
- Include both an English and a Persian capture to show RTL support
- Crop to the content area; omit the browser chrome
- Store under `docs/screenshots/` with descriptive names
  (`dashboard-dark.png`, `jobs-list-light.png`, `job-form-sources.png`)
- Keep each file under 500 KB (PNG, then optimise with `pngquant` or similar)
