# Documentation

Documentation for **Tokser Backup Manager** by **TokserTeam**.

| Document | Description |
|---|---|
| [../README.md](../README.md) | Project overview, features, installation |
| [README.fa.md](README.fa.md) | مستندات کامل فارسی |
| [USAGE.md](USAGE.md) | Screen-by-screen usage guide |
| [API.md](API.md) | REST API reference with examples |
| [SECURITY.md](SECURITY.md) | Security model, threat model, hardening |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development setup, architecture, conventions |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Diagnostics and fixes |
| [SCREENSHOTS.md](SCREENSHOTS.md) | Capturing screenshots |

## Reading order

**Installing and running it:** [../README.md](../README.md) → [USAGE.md](USAGE.md)

**Operating it day to day:** [USAGE.md](USAGE.md) → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

**Hardening a deployment:** [SECURITY.md](SECURITY.md) → [../SECURITY.md](../SECURITY.md)

**Integrating with it:** [API.md](API.md)

**Working on the code:** [DEVELOPMENT.md](DEVELOPMENT.md)

**فارسی‌زبانان:** [README.fa.md](README.fa.md)

## Quick reference

```bash
# Health
./scripts/healthcheck.sh

# Service
sudo systemctl status TBM
sudo journalctl -u TBM -n 100 --no-pager

# Logs
sudo tail -f /opt/tokser-backup-manager/logs/tokser.log

# Tests
pytest tests/ -v
python tests/run_tests.py -v      # offline

# Upgrade
sudo ./scripts/install.sh
```

## Configuration precedence

1. Built-in defaults (`app/core/config.py`)
2. `config.yaml`
3. Environment variables / `.env`
4. Values saved from the Settings page (runtime overrides for a safe subset)

## Supported platforms

Ubuntu 22.04 / 24.04, Debian 12+. Docker is supported as an alternative
deployment.
