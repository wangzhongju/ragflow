"""Exercise the worker's actual database claiming path."""

from datafactory.store.tables import RunRow
from datafactory.worker.__main__ import _claim_one, _execute


async def test_claim_changes_state_before_another_worker_can_take_the_run(app, session):
    session.add(RunRow(id="run", project_id="p", recipe_id="r", snapshot_id="s", status="queued", user_id="u1"))
    await session.commit()
    assert await _claim_one(app) == ("run", 1)
    assert await _claim_one(app) is None
    await session.refresh(await session.get(RunRow, "run"))
    assert (await session.get(RunRow, "run")).status == "running"


async def test_cancelled_claim_is_not_executed(app, session, monkeypatch):
    session.add(RunRow(id="run", project_id="p", recipe_id="r", snapshot_id="s", status="cancelled", user_id="u1"))
    await session.commit()

    async def forbidden(*args):
        raise AssertionError("Cancelled run must not execute")

    monkeypatch.setattr("datafactory.pipeline.service.ProductionService.execute_run", forbidden)
    await _execute(app, "run", 0)
