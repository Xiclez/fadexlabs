"""trabajos de las herramientas de la beta (Tracklist ID y DJ Library Upgrader)

Revision ID: 0003_tool_jobs
Revises: 0002_profile_beta_google
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_tool_jobs"
down_revision = "0002_profile_beta_google"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploading"),
        sa.Column("input_name", sa.String(255), nullable=False),
        sa.Column("input_bytes", sa.BigInteger(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_parts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON()),
    )
    # el worker toma el más antiguo en cola de cada herramienta; la web lista los del usuario
    op.create_index("ix_tool_jobs_queue", "tool_jobs", ["status", "tool", "created_at"])
    op.create_index("ix_tool_jobs_user", "tool_jobs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tool_jobs_user", table_name="tool_jobs")
    op.drop_index("ix_tool_jobs_queue", table_name="tool_jobs")
    op.drop_table("tool_jobs")
