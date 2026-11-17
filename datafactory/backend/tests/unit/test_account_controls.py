import pytest
from sqlalchemy import select

from datafactory.core.errors import BadRequest, Conflict, Forbidden
from datafactory.engine.accounts import adjust_budget, reconcile
from datafactory.store.projects import ProjectRepository
from datafactory.store.tables import AuditRow, InvocationRow, RunRow


async def _run(session):
    project = await ProjectRepository(session).create("owner", "budget", "")
    session.add(
        RunRow(
            id="run",
            project_id=project.id,
            recipe_id="r",
            snapshot_id="s",
            status="paused",
            used_tokens=10,
            reserved_tokens=20,
            invocation_count=1,
        )
    )
    session.add(
        InvocationRow(
            id="inv",
            run_id="run",
            call_key="key",
            column_name="query",
            row_key="row",
            model_id="model",
            attempt_generation=1,
            status="billed_unknown",
            token_upper_bound=20,
            request_digest="digest",
            request={},
        )
    )
    await session.commit()
    return project.id


async def test_budget_adjustment_is_atomic_and_audited(session):
    project = await _run(session)
    await adjust_budget(session, project, "run", "owner", 100, 2, "Verified development allowance")
    row = await session.get(RunRow, "run")
    assert row.max_tokens == 100
    audit = await session.scalar(select(AuditRow))
    assert audit.before["max_tokens"] == 1000000 and audit.after["max_tokens"] == 100


async def test_budget_cannot_be_below_reservations(session):
    project = await _run(session)
    with pytest.raises(BadRequest):
        await adjust_budget(session, project, "run", "owner", 29, 2, "Too low")


async def test_non_owner_cannot_reconcile(session):
    project = await _run(session)
    with pytest.raises(Forbidden):
        await reconcile(session, project, "run", "inv", "stranger", 0, "Untrusted")


async def test_reconcile_once_keeps_call_count_and_releases_reservation(session):
    project = await _run(session)
    await reconcile(session, project, "run", "inv", "owner", 8, "Provider bill checked: eight tokens")
    row = await session.get(RunRow, "run")
    assert (row.used_tokens, row.reserved_tokens, row.invocation_count) == (18, 0, 1)
    assert (await session.get(InvocationRow, "inv")).status == "reconciled"
    with pytest.raises(Conflict):
        await reconcile(session, project, "run", "inv", "owner", 8, "Duplicate")


async def test_reason_is_required(session):
    project = await _run(session)
    with pytest.raises(BadRequest):
        await adjust_budget(session, project, "run", "owner", 100, 2, "  ")
