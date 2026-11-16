"""Recipes, runs, datasets, review and releases."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_production"
down_revision: str | None = "0002_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipe",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "recipe_version",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("recipe_id", sa.String(40), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
    )
    op.create_table(
        "run",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("recipe_id", sa.String(40), nullable=False),
        sa.Column("snapshot_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "dataset",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "sample",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("dataset_id", sa.String(40), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("positives", sa.JSON, nullable=False),
        sa.Column("negatives", sa.JSON, nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("body", sa.JSON, nullable=False),
    )
    op.create_table(
        "review",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("sample_id", sa.String(40), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
    )
    op.create_table(
        "release",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("dataset_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False),
        sa.Column("gates", sa.JSON, nullable=False),
        sa.Column("samples", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for name in ("release", "review", "sample", "dataset", "run", "recipe_version", "recipe"):
        op.drop_table(name)
