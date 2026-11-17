"""Index existing frozen asset references for project-scoped downloads."""

import sqlalchemy as sa
from alembic import op

revision = "0006_asset_access"
down_revision = "0005_resumable_runs"
branch_labels = None
depends_on = None


def upgrade():
    links = op.create_table(
        "snapshot_asset",
        sa.Column("asset_id", sa.String(80), primary_key=True),
        sa.Column("snapshot_id", sa.String(40), primary_key=True),
    )
    segment = sa.table(
        "segment", sa.column("id", sa.String), sa.column("snapshot_id", sa.String), sa.column("parts", sa.JSON)
    )
    connection = op.get_bind()
    cursor = ""
    seen = set()
    while True:
        rows = (
            connection.execute(sa.select(segment).where(segment.c.id > cursor).order_by(segment.c.id).limit(1000))
            .mappings()
            .all()
        )
        if not rows:
            break
        for row in rows:
            for part in row["parts"]:
                asset = part.get("asset_id")
                key = (asset, row["snapshot_id"])
                if asset and key not in seen:
                    connection.execute(links.insert().values(asset_id=asset, snapshot_id=row["snapshot_id"]))
                    seen.add(key)
        cursor = rows[-1]["id"]


def downgrade():
    op.drop_table("snapshot_asset")
