"""Opt-in checks of the 91 deployment using synthetic, isolated development data.

Run inside df-api with DF_TEST_DEPLOYED=1. The gateway model is a stub in the
accounting race; the worker, HTTP server, MySQL and MinIO are actual services.
No RAGFlow identity, corpus or paid model is used by these tests.
"""

import asyncio
import hashlib
import io
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from datafactory.app.auth import session_cookie
from datafactory.core.execution import BudgetExceeded
from datafactory.core.ids import new_id
from datafactory.core.settings import Settings
from datafactory.domain.content import ContentPart, HealthReport, Position, Segment, SegmentOrigin
from datafactory.domain.snapshot import FrozenAsset, SnapshotDraft
from datafactory.engine.model_client import ModelClient
from datafactory.gateway.dto import Invocation, Usage
from datafactory.store.objects import MinioObjectStore
from datafactory.store.runs import RunStore
from datafactory.store.snapshots import SnapshotRepository
from datafactory.store.tables import Base, InvocationRow, RunRow, SampleRow

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("DF_TEST_DEPLOYED") != "1", reason="Opt in on 91"),
]


@pytest.fixture
async def deployed():
    settings = Settings()
    database = make_url(settings.database_url)
    assert settings.env == "dev"
    assert database.host == "df-mysql" and database.database == "datafactory_dev_91"
    assert settings.minio_endpoint == "df-minio:9000"
    assert make_url(settings.redis_url).host == "df-redis"
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user = "integration-" + uuid.uuid4().hex
    name, cookie = session_cookie(user, settings.session_secret)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9390/api/factory/v1", cookies={name: cookie}) as client:
        yield settings, sessions, client, user
    await engine.dispose()


async def test_migrated_mysql_columns_and_namespaced_redis(deployed):
    settings, sessions, _, _ = deployed
    async with sessions() as session:
        connection = await session.connection()

        def verify(sync):
            schema = inspect(sync)
            assert set(schema.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
            for name, table in Base.metadata.tables.items():
                assert {col["name"] for col in schema.get_columns(name)} == set(table.columns.keys()), name

        await connection.run_sync(verify)
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0008_release_manifest"
    redis = Redis.from_url(settings.redis_url)
    key = settings.redis_key("integration", uuid.uuid4().hex)
    try:
        assert await redis.set(key, "isolated", ex=30)
        assert await redis.get(key) == b"isolated"
    finally:
        await redis.delete(key)
        await redis.aclose()


async def test_http_asset_worker_checkpoint_and_release_gate(deployed):
    settings, sessions, client, user = deployed
    body = {"name": "Integration smoke (synthetic)", "description": "No RAGFlow content or model calls"}
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    response = await client.post("/projects", json=body, headers=headers)
    assert response.status_code == 201, response.text
    project = response.json()["id"]
    assert (await client.post("/projects", json=body, headers=headers)).json()["id"] == project
    prefix = f"/projects/{project}"
    objects = MinioObjectStore(settings)
    data = b"DataFactory isolated asset verification\n"
    digest = hashlib.sha256(data).hexdigest()
    asset = f"sha256:{digest}"
    async with sessions() as session:
        repository = SnapshotRepository(session, objects)
        snapshot = await repository.create(project, user, "Synthetic frozen corpus", [])
        segment = Segment(
            id=new_id("segment"),
            snapshot_id=snapshot.id,
            origin=SegmentOrigin(kb_id="synthetic", doc_id="synthetic", chunk_id="synthetic", content_hash=digest),
            modality="text",
            parts=[ContentPart(type="text", text="Synthetic evidence for worker validation", asset_id=asset)],
            title="Synthetic evidence",
            position=Position(),
            hash=digest,
            tokens=10,
        )
        negative = segment.model_copy(
            update={
                "id": "seg_z" + uuid.uuid4().hex,
                "origin": SegmentOrigin(
                    kb_id="synthetic", doc_id="negative", chunk_id="negative", content_hash="negative"
                ),
                "parts": [ContentPart(type="text", text="Unrelated synthetic evidence")],
            }
        )
        draft = SnapshotDraft(
            segments=[segment, negative],
            assets=[FrozenAsset(asset, data, "text/plain", "")],
            health=HealthReport(
                segment_count=2,
                document_count=2,
                modality_counts={"text": 2},
                length={},
                short_ratio=0,
                long_ratio=0,
                garbage_ratio=0,
                exact_duplicate_ratio=0,
                near_duplicate_ratio=0,
                family_count=1,
                skipped={},
                not_ready=[],
            ),
        )
        await repository.save_build(snapshot.id, draft)
    response = await client.get(f"/assets/{asset}", headers={"Range": "bytes=0-10"})
    assert response.status_code == 206 and response.content == data[:11]
    assert response.headers["content-range"] == f"bytes 0-10/{len(data)}"
    assert (
        await client.get(f"/assets/{asset}", headers={"If-None-Match": response.headers["etag"]})
    ).status_code == 304
    async with httpx.AsyncClient(base_url=str(client.base_url)) as stranger:
        assert (await stranger.get(f"/assets/{asset}")).status_code == 401
    recipe = await client.post(
        f"{prefix}/recipes",
        json={
            "name": "Expression smoke",
            "config": {
                "seed": {"type": "ragflow_snapshot", "snapshot_id": snapshot.id},
                "columns": [
                    {"name": "query", "type": "expression", "params": {"expr": "{{ seed.parts | render_parts }}"}}
                ],
                "budget": {"max_tokens": 1000, "max_invocations": 1},
            },
        },
    )
    assert recipe.status_code == 201, recipe.text
    run_body = {"recipe_id": recipe.json()["id"], "snapshot_id": snapshot.id, "limit": 1}
    run_response = await client.post(f"{prefix}/runs", json=run_body, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    for _ in range(40):
        run = (await client.get(f"{prefix}/runs/{run['id']}")).json()
        if run["status"] in {"completed", "failed", "paused"}:
            break
        await asyncio.sleep(0.25)
    assert run["status"] == "completed", run
    assert run["sample_count"] == 1 and run["invocation_count"] == 0
    metrics = (await client.get(f"{prefix}/runs/{run['id']}/metrics")).json()
    assert metrics["checkpoints"]
    async with sessions() as session:
        restored = await session.get(RunRow, run["id"])
        assert restored is not None and restored.completed_units == restored.total_units
    datasets = (await client.get(f"{prefix}/datasets")).json()
    dataset = next(item for item in datasets if item["run_id"] == run["id"])
    samples = (await client.get(f"{prefix}/datasets/{dataset['id']}/samples")).json()
    assert samples[0]["query"] == "Synthetic evidence for worker validation"
    reviewed = await client.post(
        f"{prefix}/samples/{samples[0]['id']}/reviews", json={"decision": "approved", "reason": "Fixture check"}
    )
    assert reviewed.status_code == 200
    released = await client.post(f"{prefix}/datasets/{dataset['id']}/releases")
    assert released.status_code == 201, released.text
    assert released.json()["status"] == "blocked"
    assert any(not gate["passed"] and gate["level"] == "blocker" for gate in released.json()["gates"])

    # Install a known valid synthetic fixture to test packaging, not model quality.
    async with sessions() as session:
        sample = await session.get(SampleRow, samples[0]["id"])
        assert sample is not None
        sample.negatives = [negative.id]
        sample.body = {**sample.body, "negatives": [negative.id], "judge": {"overall": 8}}
        await session.commit()
    valid = await client.post(f"{prefix}/datasets/{dataset['id']}/releases")
    assert valid.status_code == 201 and valid.json()["status"] == "released", valid.text
    url = f"{prefix}/releases/{valid.json()['id']}/package"
    packaged = await client.get(url)
    assert packaged.status_code == 200, packaged.text
    assert packaged.content == (await client.get(url)).content
    with ZipFile(io.BytesIO(packaged.content)) as archive:
        assert archive.read(f"assets/{digest}") == data
        manifest = json.loads(archive.read("manifest.json"))
        for name, meta in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == meta["sha256"]


async def test_mysql_concurrent_reservation_cannot_overspend(deployed):
    settings, sessions, _, user = deployed
    run_id = new_id("run")
    async with sessions() as session:
        session.add(
            RunRow(
                id=run_id,
                project_id="integration",
                recipe_id="synthetic",
                snapshot_id="synthetic",
                status="running",
                user_id=user,
                max_invocations=1,
                max_tokens=10000,
                lease_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
            )
        )
        await session.commit()
    gateway = AsyncMock()
    gateway.invoke.return_value = Invocation(
        outputs={"text": "fixture"}, usage=Usage(total_tokens=15), latency_ms=1, model_fingerprint="fixture"
    )

    async def invoke(index):
        async with sessions() as session:
            model = ModelClient(gateway, RunStore(session, MinioObjectStore(settings), run_id, 0))
            return await model.invoke(
                "fixture", "chat", {"prompt": "fixture"}, {"max_tokens": 10}, column="query", row_key=str(index)
            )

    outcomes = await asyncio.gather(invoke(1), invoke(2), return_exceptions=True)
    assert sum(isinstance(item, BudgetExceeded) for item in outcomes) == 1, outcomes
    gateway.invoke.assert_awaited_once()
    async with sessions() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None and (run.invocation_count, run.used_tokens, run.reserved_tokens) == (1, 15, 0)
        assert len((await session.scalars(select(InvocationRow).where(InvocationRow.run_id == run_id))).all()) == 1
        run.status = "completed"
        run.lease_until = None
        await session.commit()
