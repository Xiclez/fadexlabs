"""perfil (WhatsApp, aviso de privacidad), beta cerrada y login con Google

Revision ID: 0002_profile_beta_google
Revises: 0001_auth
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_profile_beta_google"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:  # batch: también funciona en SQLite (desarrollo)
        b.add_column(sa.Column("whatsapp", sa.String(20)))
        b.add_column(sa.Column("privacy_accepted_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("google_sub", sa.String(64)))
        b.add_column(sa.Column("beta_seat", sa.Integer()))
        b.create_unique_constraint("uq_users_google_sub", ["google_sub"])
        b.create_unique_constraint("uq_users_beta_seat", ["beta_seat"])


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_beta_seat", type_="unique")
        b.drop_constraint("uq_users_google_sub", type_="unique")
        b.drop_column("beta_seat")
        b.drop_column("google_sub")
        b.drop_column("privacy_accepted_at")
        b.drop_column("whatsapp")
