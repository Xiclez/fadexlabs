"""detener trabajos y encuesta al terminar (web y app de escritorio)

Revision ID: 0005_stop_and_feedback
Revises: 0004_desktop_sessions
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_stop_and_feedback"
down_revision = "0004_desktop_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_jobs") as b:  # batch: también funciona en SQLite (desarrollo)
        b.add_column(sa.Column("stop_requested_at", sa.DateTime(timezone=True)))
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("tool", sa.String(24), nullable=False),
        sa.Column("job_ref", sa.String(64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(500), nullable=False, server_default=""),
        sa.Column("stopped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "job_ref", name="uq_feedback_user_job"),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_table("feedback")
    with op.batch_alter_table("tool_jobs") as b:
        b.drop_column("stop_requested_at")
