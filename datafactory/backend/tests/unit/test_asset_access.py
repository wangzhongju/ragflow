import hashlib

import pytest

from datafactory.store.projects import ProjectRepository
from datafactory.store.tables import AssetRow, SnapshotAssetRow, SnapshotRow


async def _asset(session, app, user="u1"):
    project = await ProjectRepository(session).create(user, "assets", "")
    data = b"0123456789"
    asset_id = "sha256:" + hashlib.sha256(data).hexdigest()
    uri = app.state.objects.put_asset(asset_id, data, "image/png")
    session.add(AssetRow(asset_id=asset_id, mime="image/png", size=len(data), storage_uri=uri))
    session.add(
        SnapshotRow(id="snapshot", project_id=project.id, name="s", status="ready", sources=[], created_by=user)
    )
    session.add(SnapshotAssetRow(asset_id=asset_id, snapshot_id="snapshot"))
    await session.commit()
    return f"/api/factory/v1/assets/{asset_id}", asset_id


@pytest.mark.parametrize(
    "requested,status,body",
    [
        ("bytes=2-5", 206, b"2345"),
        ("bytes=-3", 206, b"789"),
        ("bytes=7-", 206, b"789"),
        ("bytes=0-999", 206, b"0123456789"),
        ("bytes=10-", 416, b""),
        ("bytes=-0", 416, b""),
        ("bytes=1-2,4-5", 416, b""),
        ("bytes=6-1", 416, b""),
        ("bytes=-", 416, b""),
    ],
)
async def test_authenticated_ranges(client, session, app, requested, status, body):
    url, _ = await _asset(session, app)
    response = await client.get(url, headers={"Range": requested})
    assert response.status_code == status
    assert response.content == body
    assert response.headers["accept-ranges"] == "bytes"


async def test_conditional_requests_still_require_membership(client, session, app):
    url, asset = await _asset(session, app, "another-user")
    response = await client.get(url, headers={"If-None-Match": f'"{asset}"'})
    assert response.status_code == 404


async def test_etag_and_if_range(client, session, app):
    url, asset = await _asset(session, app)
    assert (await client.get(url, headers={"If-None-Match": f'"{asset}"'})).status_code == 304
    response = await client.get(url, headers={"If-Range": '"old"', "Range": "bytes=2-3"})
    assert response.status_code == 200 and len(response.content) == 10


async def test_corrupt_frozen_bytes_cannot_be_served(client, session, app):
    url, asset = await _asset(session, app)
    row = await session.get(AssetRow, asset)
    row.size += 1
    await session.commit()
    assert (await client.get(url)).status_code == 409
