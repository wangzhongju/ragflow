"""Frozen run inputs, fenced checkpoints and a durable invocation ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0005_resumable_runs"
down_revision = "0004_runtime_integrity"
branch_labels = None
depends_on = None

_INTS = {
    "seed": 1,
    "batch_size": 64,
    "attempt_generation": 0,
    "completed_units": 0,
    "total_units": 0,
    "max_invocations": 1000,
    "max_tokens": 1000000,
    "reserved_tokens": 0,
    "used_tokens": 0,
    "invocation_count": 0,
}


def upgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch:
        batch.create_unique_constraint("uq_recipe_version_number", ["recipe_id", "number"])
    op.add_column("run", sa.Column("recipe_version_id", sa.String(40), nullable=False, server_default=""))
    op.add_column("run", sa.Column("mode", sa.String(16), nullable=False, server_default="run"))
    for name, default in _INTS.items():
        op.add_column("run", sa.Column(name, sa.Integer, nullable=False, server_default=str(default)))
    op.add_column("run", sa.Column("lease_until", sa.DateTime, nullable=True))
    op.add_column("run", sa.Column("preview", sa.JSON, nullable=True))
    op.execute(sa.text("UPDATE run SET preview = '[]'"))
    with op.batch_alter_table("run") as batch:
        batch.alter_column("preview", existing_type=sa.JSON, nullable=False)
    op.execute(
        sa.text(
            "UPDATE run SET status = 'failed', error = 'Run has no frozen recipe version; create a new run.' "
            "WHERE status IN ('queued', 'running')"
        )
    )
    op.create_table(
        "run_checkpoint",
        sa.Column("run_id", sa.String(40), primary_key=True),
        sa.Column("stage", sa.Integer, primary_key=True),
        sa.Column("batch", sa.Integer, primary_key=True),
        sa.Column("attempt_generation", sa.Integer, nullable=False),
        sa.Column("column_name", sa.String(200), nullable=False),
        sa.Column("object_key", sa.String(300), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("elapsed_ms", sa.Integer, nullable=False),
    )
    op.create_table(
        "invocation",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("call_key", sa.String(64), nullable=False),
        sa.Column("column_name", sa.String(200), nullable=False),
        sa.Column("row_key", sa.Text, nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("model_fingerprint", sa.String(200), nullable=False),
        sa.Column("attempt_generation", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("token_upper_bound", sa.Integer, nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("response", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "call_key", name="uq_invocation_call"),
    )
    op.create_index("ix_invocation_run_id", "invocation", ["run_id"])


def downgrade() -> None:
    op.drop_table("invocation")
    op.drop_table("run_checkpoint")
    with op.batch_alter_table("run") as batch:
        for name in ["recipe_version_id", "mode", "lease_until", "preview", *_INTS]:
            batch.drop_column(name)
    with op.batch_alter_table("recipe_version") as batch:
        batch.drop_constraint("uq_recipe_version_number", type_="unique")
