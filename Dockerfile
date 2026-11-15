# Tokser Backup Manager — container image
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TBM_DATA_DIR=/data \
    TBM_BACKUP_DIR=/backups \
    TBM_LOG_DIR=/logs

# Runtime tools for archive + database operations.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tar gzip zip unzip zstd \
        ca-certificates curl \
        default-mysql-client postgresql-client \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY systemd ./systemd
COPY migrations ./migrations 2>/dev/null || true
COPY config.example.yaml ./
COPY alembic.ini ./ 2>/dev/null || true

# Run unprivileged.
RUN groupadd --system --gid 10001 tokser \
    && useradd --system --uid 10001 --gid tokser --create-home --home-dir /app tokser \
    && mkdir -p /data /backups /logs \
    && chown -R tokser:tokser /app /data /backups /logs

USER tokser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
