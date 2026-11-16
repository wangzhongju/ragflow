"""Snapshots, health checks and document families."""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_snapshots"
down_revision: str | None = "0001_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("vector_profile", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "source_document",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("snapshot_id", sa.String(40), nullable=False),
        sa.Column("kb_id", sa.String(64), nullable=False),
        sa.Column("doc_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("suffix", sa.String(32), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column("family_id", sa.String(80), nullable=True),
        sa.UniqueConstraint("snapshot_id", "doc_id"),
    )
    op.create_table(
        "segment",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("snapshot_id", sa.String(40), nullable=False),
        sa.Column("origin_kb_id", sa.String(64), nullable=False),
        sa.Column("origin_doc_id", sa.String(64), nullable=False),
        sa.Column("origin_chunk_id", sa.String(64), nullable=False),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("parts", sa.JSON, nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("position", sa.JSON, nullable=False),
        sa.Column("parent_segment_id", sa.String(40), nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("minhash", sa.JSON, nullable=False),
        sa.Column("tokens", sa.Integer, nullable=False),
        sa.Column("meta", sa.JSON, nullable=False),
        sa.UniqueConstraint("snapshot_id", "origin_chunk_id"),
    )
    op.create_table(
        "asset",
        sa.Column("asset_id", sa.String(80), primary_key=True),
        sa.Column("mime", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("asset")
    op.drop_table("segment")
    op.drop_table("source_document")
    op.drop_table("snapshot")
