"""Configuration loading tests.

Regression coverage for a shipped bug: config.example.yaml carries blank
strings for auto-derived fields (``database_url``, ``backup_dir``), and a
naive precedence check treated those blanks as real values, producing an
empty SQLAlchemy URL and a crash on import in a fresh installation.

The helper below manipulates ``os.environ`` directly and restores it in a
``finally`` block, so these tests run identically under pytest and the
bundled offline runner (which does not implement ``monkeypatch``).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def _sandbox(tmp_path: Path, config_yaml: str | None = None, env: dict[str, str] | None = None):
    """Point app.core.config at a temporary tree, then restore everything."""
    import app.core.config as cfg

    # Every TBM_* variable is cleared so session-wide settings from conftest
    # (notably TBM_SCHEDULER=false) cannot leak into these assertions.
    keys = tuple(k for k in os.environ if k.startswith("TBM_")) + (
        "TBM_DATA_DIR", "TBM_BACKUP_DIR", "TBM_LOG_DIR", "TBM_DATABASE_URL",
        "TBM_SECRET_KEY", "TBM_ENCRYPTION_KEY", "TBM_HOST", "TBM_PORT",
        "TBM_SCHEDULER",
    )
    saved_env = {k: os.environ.get(k) for k in keys}
    saved_attrs = {
        name: getattr(cfg, name)
        for name in ("BASE_DIR", "DATA_DIR", "BACKUP_DIR", "LOG_DIR", "TMP_DIR")
    }
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ["TBM_DATA_DIR"] = str(tmp_path / "data")
        os.environ["TBM_BACKUP_DIR"] = str(tmp_path / "backups")
        os.environ["TBM_LOG_DIR"] = str(tmp_path / "logs")
        os.environ.update(env or {})

        if config_yaml is not None:
            (tmp_path / "config.yaml").write_text(config_yaml, encoding="utf-8")

        cfg.BASE_DIR = tmp_path
        cfg.DATA_DIR = tmp_path / "data"
        cfg.BACKUP_DIR = tmp_path / "backups"
        cfg.LOG_DIR = tmp_path / "logs"
        cfg.TMP_DIR = tmp_path / "data" / "tmp"
        yield cfg, tmp_path
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name, value in saved_attrs.items():
            setattr(cfg, name, value)


def test_blank_yaml_values_fall_back_to_defaults(tmp_path):
    with _sandbox(tmp_path, 'database_url: ""\nbackup_dir: ""\n'
                            'secret_key: ""\nencryption_key: ""\n') as (cfg, tmp):
        settings = cfg.Settings()
        assert settings.database_url, "database_url must never be empty"
        assert settings.database_url.startswith("sqlite:///")
        assert "tokser.db" in settings.database_url
        assert settings.backup_dir
        assert settings.secret_key
        assert settings.encryption_key


def test_blank_values_produce_a_usable_engine(tmp_path):
    from sqlalchemy import create_engine

    with _sandbox(tmp_path, 'database_url: ""\n') as (cfg, _):
        settings = cfg.Settings()
        engine = create_engine(settings.database_url)  # must not raise
        assert engine.url.database


def test_explicit_yaml_value_is_respected(tmp_path):
    target = tmp_path / "custom.db"
    with _sandbox(tmp_path, f'database_url: "sqlite:///{target.as_posix()}"\n') as (cfg, _):
        settings = cfg.Settings()
        assert settings.database_url.endswith("custom.db")


def test_environment_overrides_yaml(tmp_path):
    with _sandbox(tmp_path, "port: 9999\n", env={"TBM_PORT": "8123"}) as (cfg, _):
        settings = cfg.Settings()
        assert settings.port == 8123


def test_blank_env_falls_through(tmp_path):
    with _sandbox(tmp_path, env={"TBM_HOST": ""}) as (cfg, _):
        settings = cfg.Settings()
        assert settings.host == "127.0.0.1"


def test_secrets_are_generated_and_persisted(tmp_path):
    with _sandbox(tmp_path) as (cfg, tmp):
        first = cfg.Settings()
        second = cfg.Settings()
        assert first.secret_key == second.secret_key, "generated key must be stable"
        assert (tmp / "data" / ".secret_key").exists()
        assert (tmp / "data" / ".encryption_key").exists()


def test_shipped_example_config_loads(tmp_path):
    """The example file must be usable as-is — the installer copies it."""
    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    if not example.exists():
        pytest.skip("config.example.yaml not found")
    with _sandbox(tmp_path, example.read_text(encoding="utf-8")) as (cfg, _):
        settings = cfg.Settings()
        assert settings.database_url.startswith("sqlite:///")
        assert settings.backup_dir
        assert settings.port == 8000
        assert settings.scheduler_enabled is True
