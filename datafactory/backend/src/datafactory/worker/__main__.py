"""Claim queued runs atomically and execute them under the submitting user."""

import asyncio

from datafactory.core.settings import Settings


def main() -> None:
    """Run the worker until interrupted."""
    settings = Settings()
    asyncio.run(_serve(settings))


async def _serve(settings: Settings) -> None:
    from datafactory.app.main import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        while True:
            claimed = await _claim_one(app)
            if claimed is None:
                await asyncio.sleep(2)
                continue
            await _execute(app, *claimed)


async def _claim_one(app) -> tuple[str, int] | None:
    """Claim a queued or expired run and return its id and fencing generation."""
    from datetime import UTC, datetime

    from sqlalchemy import and_, or_, select, update

    from datafactory.store.runs import lease_deadline
    from datafactory.store.tables import InvocationRow, RunRow

    async with app.state.sessions() as session:
        eligible = or_(
            RunRow.status == "queued",
            and_(
                RunRow.status == "running",
                RunRow.lease_until < datetime.now(UTC).replace(tzinfo=None),
            ),
        )
        run = await session.scalar(select(RunRow).where(eligible).order_by(RunRow.mode, RunRow.id).limit(1))
        if run is None:
            return None
        run_id, generation = run.id, run.attempt_generation + 1
        claimed = await session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, eligible, RunRow.attempt_generation == generation - 1)
            .values(status="running", attempt_generation=generation, lease_until=lease_deadline())
        )
        if claimed.rowcount != 1:
            await session.rollback()
            return None
        uncertain = await session.scalar(
            select(InvocationRow.id)
            .where(
                InvocationRow.run_id == run_id,
                InvocationRow.status.in_(("sent", "billed_unknown")),
            )
            .limit(1)
        )
        if uncertain:
            await session.execute(
                update(InvocationRow)
                .where(
                    InvocationRow.run_id == run_id,
                    InvocationRow.status == "sent",
                )
                .values(status="billed_unknown")
            )
            await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id)
                .values(
                    status="paused",
                    lease_until=None,
                    error=f"Invocation {uncertain} has an uncertain outcome.",
                )
            )
        await session.commit()
        return None if uncertain else (run_id, generation)


async def _execute(app, run_id: str, generation: int) -> None:
    """Run one claimed job. A gateway bound to the run's user drives model calls."""
    from datafactory.core.settings import GatewaySettings
    from datafactory.gateway.client import GatewayClient
    from datafactory.pipeline.service import ProductionService
    from datafactory.store.tables import RunRow

    async with app.state.sessions() as session:
        run = await session.get(RunRow, run_id)
        if run is None or run.status != "running" or run.attempt_generation != generation:
            return
        gateway = GatewayClient(GatewaySettings.model_validate(app.state.settings.model_dump()), run.user_id, run_id)
        await ProductionService(session, gateway, app.state.objects).execute_run(run_id, generation)


if __name__ == "__main__":
    main()
