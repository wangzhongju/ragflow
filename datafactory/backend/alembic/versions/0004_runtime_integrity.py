"""Persist creation keys and align run fields with the runtime."""

import sqlalchemy as sa
from alembic import op

revision = "0004_runtime_integrity"
down_revision = "0003_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency",
        sa.Column("scope", sa.String(200), primary_key=True),
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(40), nullable=False),
    )
    op.add_column("run", sa.Column("limit_n", sa.Integer, nullable=False, server_default="0"))
    op.add_column("run", sa.Column("error", sa.Text, nullable=False, server_default=""))
    op.add_column("run", sa.Column("user_id", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("run") as batch:
        batch.drop_column("user_id")
        batch.drop_column("error")
        batch.drop_column("limit_n")
    op.drop_table("idempotency")
