"""Authorized access to immutable asset bytes."""

import asyncio
import hashlib
import re

from sqlalchemy import select

from datafactory.core.errors import Conflict, NotFound
from datafactory.store.tables import AssetRow, MemberRow, SnapshotAssetRow, SnapshotRow


async def read_asset(session, objects, asset_id, user_id):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", asset_id):
        raise NotFound("Asset not found.")
    access = await session.scalar(
        select(SnapshotAssetRow.asset_id)
        .join(SnapshotRow, SnapshotRow.id == SnapshotAssetRow.snapshot_id)
        .join(MemberRow, MemberRow.project_id == SnapshotRow.project_id)
        .where(
            SnapshotAssetRow.asset_id == asset_id,
            MemberRow.user_id == user_id,
            SnapshotRow.status.in_(("ready", "stale")),
        )
        .limit(1)
    )
    if access is None:
        raise NotFound("Asset not found.")
    asset = await session.get(AssetRow, asset_id)
    if asset is None:
        raise NotFound("Asset not found.")
    data, _ = await asyncio.to_thread(objects.get_asset, asset_id)
    if len(data) != asset.size or hashlib.sha256(data).hexdigest() != asset_id.removeprefix("sha256:"):
        raise Conflict("Frozen asset failed integrity verification.", code="asset_corrupt")
    return data, asset.mime
