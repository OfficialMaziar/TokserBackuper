"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-12

Creates the complete Tokser Backup Manager schema. Table and index
definitions are taken from the SQLAlchemy metadata so the migration can
never drift from the models; ``checkfirst=True`` makes it safe to run
against a database that was bootstrapped with ``Base.metadata.create_all``.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.database import Base
from app import models  # noqa: F401  (register all mappers)

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Dependency order is resolved by sorted_tables (parents before children).
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        table.create(bind=bind, checkfirst=True)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
