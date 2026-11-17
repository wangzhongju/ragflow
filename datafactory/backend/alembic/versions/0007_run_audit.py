"""Audit run budget adjustments and manual billing reconciliations."""

import sqlalchemy as sa
from alembic import op

revision = "0007_run_audit"
down_revision = "0006_asset_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(40), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("before", sa.JSON, nullable=False),
        sa.Column("after", sa.JSON, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_project_id", "audit", ["project_id"])


def downgrade():
    op.drop_table("audit")
