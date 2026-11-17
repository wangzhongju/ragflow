"""Freeze provenance and acknowledged warnings with a release."""

import sqlalchemy as sa
from alembic import op

revision = "0008_release_manifest"
down_revision = "0007_run_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("release", sa.Column("manifest", sa.JSON, nullable=True))
    op.execute(sa.text("UPDATE `release` SET manifest = '{}'"))
    with op.batch_alter_table("release") as batch:
        batch.alter_column("manifest", existing_type=sa.JSON, nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("release") as batch:
        batch.drop_column("manifest")
