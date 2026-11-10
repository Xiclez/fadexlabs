"""sesiones de la app de escritorio (DJ Library Upgrader para Windows)

Revision ID: 0004_desktop_sessions
Revises: 0003_tool_jobs
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_desktop_sessions"
down_revision = "0003_tool_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("refresh_tokens") as b:  # batch: también funciona en SQLite (desarrollo)
        b.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="web"))


def downgrade() -> None:
    with op.batch_alter_table("refresh_tokens") as b:
        b.drop_column("kind")
