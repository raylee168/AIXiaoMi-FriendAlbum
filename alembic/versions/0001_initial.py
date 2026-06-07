"""initial friend album schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-07
"""
from alembic import op

from app.db.base import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in {"photo_files", "plugin_events"}:
            table.drop(bind=op.get_bind(), checkfirst=True)
