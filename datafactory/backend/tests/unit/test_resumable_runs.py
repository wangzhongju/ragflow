"""Crash, cancellation, budget and immutable-input regressions without external services."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, update

from datafactory.core.errors import Conflict, GatewayUnavailable
from datafactory.core.execution import BilledUnknown, BudgetExceeded, RunInterrupted
from datafactory.engine.model_client import ModelClient
from datafactory.engine.recipes import RecipeRepository
from datafactory.gateway.dto import Invocation, Usage
from datafactory.pipeline.service import ProductionService
from datafactory.store.projects import ProjectRepository
from datafactory.store.runs import RunStore
from datafactory.store.tables import (
    DatasetRow,
    InvocationRow,
    RecipeRow,
    RunCheckpointRow,
    RunRow,
    SampleRow,
    SegmentRow,
    SnapshotRow,
)
from datafactory.worker.__main__ import _claim_one


async def _claim(app) -> tuple[str, int]:
    claimed = await _claim_one(app)
    assert claimed is not None
    return claimed


async def _arrange(session, app, *, columns=None, count=3, budget=None):
    project = await ProjectRepository(session).create("u1", "Runs", "")
    session.add(
        SnapshotRow(id="snap", project_id=project.id, name="Frozen", status="ready", sources=[], created_by="u1")
    )
    for i in range(count):
        session.add(
            SegmentRow(
                id=f"seg_{i:04}",
                snapshot_id="snap",
                origin_kb_id="kb",
                origin_doc_id="doc",
                origin_chunk_id=f"chunk_{i}",
                modality="text",
                parts=[{"type": "text", "text": f"passage {i}"}],
                position={},
                content_hash=f"h{i}",
                tokens=2,
            )
        )
    await session.commit()
    recipe = await RecipeRepository(session).create(
        project.id,
        "u1",
        "Original",
        {
            "seed": {"type": "ragflow_snapshot", "snapshot_id": "snap"},
            "columns": columns
            or [{"name": "query", "type": "expression", "params": {"expr": "{{ seed.parts | render_parts }}"}}],
            "models": {"generator": {"model_id": "model"}},
            "run": {"seed": 17, "batch_size": 2},
            "budget": budget or {},
        },
    )
    gateway = AsyncMock()
    gateway.invoke.return_value = Invocation(
        outputs={"text": "Question?"}, usage=Usage(total_tokens=12), latency_ms=3, model_fingerprint="fp"
    )
    return project.id, recipe.id, ProductionService(session, gateway, app.state.objects), gateway


async def test_run_binds_version_before_draft_changes_and_does_not_truncate_corpus(session, app, monkeypatch):
    project, recipe_id, service, _ = await _arrange(session, app, count=1002)
    run = await service.start_run(project, "u1", recipe_id, "snap", 1)
    assert run.recipe_version_id
    row = await session.get(RecipeRow, recipe_id)
    row.config = {**row.config, "columns": [{"name": "query", "type": "expression", "params": {"expr": "changed"}}]}
    await session.commit()
    import datafactory.pipeline.run as executor

    original = executor.execute

    async def inspect_corpus(column, rows, *args):
        assert len(rows[0]["_corpus"]) == 1002
        return await original(column, rows, *args)

    monkeypatch.setattr(executor, "execute", inspect_corpus)
    claimed = await _claim(app)
    finished = await service.execute_run(*claimed)
    assert finished.status == "completed", finished.error
    assert finished.seed == 17
    sample = await session.scalar(select(SampleRow))
    assert sample.query == "passage 0"
    assert sample.body["lineage"]["recipe_version_id"] == run.recipe_version_id


async def test_pause_resume_uses_committed_batches_without_reexecuting_them(session, app, monkeypatch):
    project, recipe, service, _ = await _arrange(session, app)
    run = await service.start_run(project, "u1", recipe, "snap", 3)
    original = RunStore.save
    calls = []

    async def save_and_pause(store, stage, batch, *args):
        calls.append((stage, batch))
        await original(store, stage, batch, *args)
        if len(calls) == 1:
            await service.control_run(project, run.id, "u1", "pause")

    monkeypatch.setattr(RunStore, "save", save_and_pause)
    stopped = await service.execute_run(*(await _claim(app)))
    assert stopped.status == "paused"
    assert stopped.completed_units == 1
    await service.control_run(project, run.id, "u1", "resume")
    finished = await service.execute_run(*(await _claim(app)))
    assert finished.status == "completed", finished.error
    assert finished.sample_count == 3
    assert calls == [(0, 0), (0, 1)]
    assert await session.scalar(select(func.count()).select_from(DatasetRow)) == 1


async def test_cancel_fences_checkpoint_and_dataset_writes(session, app):
    project, recipe, service, _ = await _arrange(session, app)
    run = await service.start_run(project, "u1", recipe, "snap", 2)
    _, generation = await _claim(app)
    store = RunStore(session, app.state.objects, run.id, generation)
    await service.control_run(project, run.id, "u1", "cancel")
    with pytest.raises(RunInterrupted):
        await store.save(0, 0, "query", [{"row_key": "row", "query": "late"}], 1)
    assert await session.scalar(select(func.count()).select_from(RunCheckpointRow)) == 0
    assert (await service.execute_run(run.id, generation)).status == "cancelled"
    assert await session.scalar(select(func.count()).select_from(DatasetRow)) == 0


async def test_expired_lease_claim_fences_the_previous_attempt(session, app):
    project, recipe, service, _ = await _arrange(session, app)
    run = await service.start_run(project, "u1", recipe, "snap", 2)
    first = await _claim(app)
    await session.execute(
        update(RunRow)
        .where(RunRow.id == run.id)
        .values(
            lease_until=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
    )
    await session.commit()
    second = await _claim(app)
    assert second == (run.id, first[1] + 1)
    with pytest.raises(RunInterrupted):
        await RunStore(session, app.state.objects, *first).check()
    assert (await service.execute_run(*second)).status == "completed"


async def test_preview_is_queued_and_uses_same_executor_without_dataset(client, session, app):
    project, recipe, service, _ = await _arrange(session, app)
    path = f"/api/factory/v1/projects/{project}/recipes/{recipe}:preview"
    response = await client.post(path, json={"snapshot_id": "snap", "limit": 2}, headers={"Idempotency-Key": "preview"})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    replay = await client.post(path, json={"snapshot_id": "snap", "limit": 2}, headers={"Idempotency-Key": "preview"})
    assert replay.json()["id"] == response.json()["id"]
    conflict = await client.post(path, json={"snapshot_id": "snap", "limit": 3}, headers={"Idempotency-Key": "preview"})
    assert conflict.status_code == 409
    finished = await service.execute_run(*(await _claim(app)))
    assert finished.status == "completed", finished.error
    assert len(finished.preview) == 2
    assert await session.scalar(select(func.count()).select_from(DatasetRow)) == 0
    events = await client.get(f"/api/factory/v1/projects/{project}/runs/{finished.id}/events")
    assert "event: run\n" in events.text
    assert '"status":"completed"' in events.text


async def _model(session, app, *, max_calls=2, max_tokens=10000):
    session.add(
        RunRow(
            id="run",
            project_id="p",
            recipe_id="r",
            snapshot_id="s",
            status="running",
            max_invocations=max_calls,
            max_tokens=max_tokens,
        )
    )
    await session.commit()
    gateway = AsyncMock()
    gateway.invoke.return_value = Invocation(
        outputs={"text": "Answer"}, usage=Usage(total_tokens=13), latency_ms=4, model_fingerprint="fp"
    )
    return ModelClient(gateway, RunStore(session, app.state.objects, "run", 0)), gateway


async def test_model_reserves_before_send_settles_actual_and_replays_success(session, app):
    model, gateway = await _model(session, app, max_calls=1)
    result = gateway.invoke.return_value

    async def inspect(*args):
        row = await session.get(RunRow, "run")
        assert row.reserved_tokens > 13
        assert row.invocation_count == 1
        assert (await session.scalar(select(InvocationRow))).status == "sent"
        return result

    gateway.invoke.side_effect = inspect
    args = ("model", "chat", {"history": [{"content": "private prompt"}]})
    assert await model.invoke(*args, column="query", row_key="row") == result
    assert await model.invoke(*args, column="query", row_key="row") == result
    assert gateway.invoke.call_count == 1
    with pytest.raises(BudgetExceeded):
        await model.invoke(*args, column="query", row_key="other")
    row = await session.get(RunRow, "run", populate_existing=True)
    assert (row.used_tokens, row.reserved_tokens, row.invocation_count) == (13, 0, 1)
    record = await session.scalar(select(InvocationRow))
    assert "private prompt" not in str(record.request)


async def test_uncertain_result_keeps_reservation_and_cannot_be_resent(session, app):
    model, gateway = await _model(session, app)
    gateway.invoke.side_effect = httpx.ReadTimeout("Provider may have billed this request")
    for _ in range(2):
        with pytest.raises(BilledUnknown):
            await model.invoke("model", "chat", {}, column="query", row_key="row")
    assert gateway.invoke.call_count == 1
    record = await session.scalar(select(InvocationRow))
    assert record.status == "billed_unknown"
    row = await session.get(RunRow, "run", populate_existing=True)
    assert row.reserved_tokens == record.token_upper_bound


async def test_success_without_usage_retains_reservation_without_inventing_actual_cost(session, app):
    model, gateway = await _model(session, app)
    gateway.invoke.return_value.usage = Usage()
    await model.invoke("model", "chat", {}, column="query", row_key="row")
    row = await session.get(RunRow, "run", populate_existing=True)
    assert row.used_tokens == 0
    assert row.reserved_tokens > 0
    assert (await session.scalar(select(InvocationRow))).status == "succeeded"


async def test_independent_workers_cannot_overdraw_the_same_budget(tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from datafactory.store.objects import MemoryObjectStore
    from datafactory.store.tables import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'budget.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                RunRow(id="run", project_id="p", recipe_id="r", snapshot_id="s", status="running", max_invocations=1)
            )
            await session.commit()
        gateway = AsyncMock()
        gateway.invoke.return_value = Invocation(
            outputs={"text": "q"}, usage=Usage(total_tokens=10), latency_ms=1, model_fingerprint="fp"
        )

        async def call(row_key):
            async with sessions() as session:
                model = ModelClient(gateway, RunStore(session, MemoryObjectStore(), "run", 0))
                return await model.invoke("model", "chat", {}, column="query", row_key=row_key)

        results = await asyncio.gather(call("first"), call("second"), return_exceptions=True)
        assert sum(isinstance(result, BudgetExceeded) for result in results) == 1
        assert gateway.invoke.call_count == 1
        async with sessions() as session:
            run = await session.get(RunRow, "run")
            assert run is not None
            assert (run.invocation_count, run.used_tokens, run.reserved_tokens) == (1, 10, 0)
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connect"),
        httpx.ConnectTimeout("connect"),
        GatewayUnavailable("limited", gateway_code=429),
    ],
)
async def test_definite_presend_failure_releases_reserved_tokens(session, app, error):
    model, gateway = await _model(session, app)
    gateway.invoke.side_effect = error
    with pytest.raises(type(error)):
        await model.invoke("model", "chat", {}, column="query", row_key="row")
    assert (await session.get(RunRow, "run", populate_existing=True)).reserved_tokens == 0
    assert (await session.scalar(select(InvocationRow))).status == "rejected"


@pytest.mark.parametrize("policy,status", [("pause", "paused"), ("fail", "failed")])
async def test_budget_control_is_not_swallowed_by_drop_row_policy(session, app, policy, status):
    project, recipe, service, gateway = await _arrange(
        session,
        app,
        columns=[{"name": "query", "type": "llm_text", "model": "generator", "prompt": "Question?"}],
        budget={"max_tokens": 1, "on_exceed": policy},
    )
    await service.start_run(project, "u1", recipe, "snap", 2)
    result = await service.execute_run(*(await _claim(app)))
    assert result.status == status, result.error
    assert gateway.invoke.call_count == 0


async def test_resume_rejects_uncertain_calls_and_metrics_are_project_scoped(session, app, client):
    project, recipe, service, gateway = await _arrange(
        session,
        app,
        columns=[{"name": "query", "type": "llm_text", "model": "generator", "prompt": "Question?"}],
    )
    gateway.invoke.side_effect = httpx.ReadTimeout("unknown")
    run = await service.start_run(project, "u1", recipe, "snap", 2)
    result = await service.execute_run(*(await _claim(app)))
    assert result.status == "paused"
    with pytest.raises(Conflict, match="uncertain"):
        await service.control_run(project, run.id, "u1", "resume")
    metrics = await client.get(f"/api/factory/v1/projects/{project}/runs/{run.id}/metrics")
    assert metrics.json()["invocations"][0]["status"] == "billed_unknown"
    other = await ProjectRepository(session).create("u1", "Other", "")
    denied = await client.get(f"/api/factory/v1/projects/{other.id}/runs/{run.id}/metrics")
    assert denied.status_code == 404


async def test_crash_after_dispatch_is_paused_on_lease_recovery(session, app):
    model, gateway = await _model(session, app)

    async def crash(*args):
        raise SystemExit("worker stopped after dispatch")

    gateway.invoke.side_effect = crash
    with pytest.raises(SystemExit):
        await model.invoke("model", "chat", {}, column="query", row_key="row")
    await session.execute(
        update(RunRow)
        .where(RunRow.id == "run")
        .values(
            lease_until=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
    )
    await session.commit()
    assert await _claim_one(app) is None
    assert (await session.get(RunRow, "run", populate_existing=True)).status == "paused"
    assert (
        await session.scalar(select(InvocationRow).execution_options(populate_existing=True))
    ).status == "billed_unknown"
    assert gateway.invoke.call_count == 1
