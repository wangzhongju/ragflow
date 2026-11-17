"""Owner-authorized budget changes and explicit reconciliation of uncertain bills."""

from sqlalchemy import select, update

from datafactory.core.errors import BadRequest, Conflict, NotFound
from datafactory.core.ids import new_id
from datafactory.store.projects import ProjectRepository
from datafactory.store.tables import AuditRow, InvocationRow, RunRow


async def adjust_budget(session, project_id, run_id, user_id, max_tokens, max_invocations, reason):
    run = await _locked_run(session, project_id, run_id, user_id, reason)
    if run.status not in {"paused", "queued", "blocked"}:
        raise Conflict("Pause the run before adjusting its budget.")
    if max_tokens < run.used_tokens + run.reserved_tokens or max_invocations < run.invocation_count:
        raise BadRequest("Budget cannot be lower than consumed and reserved amounts.")
    before = {"max_tokens": run.max_tokens, "max_invocations": run.max_invocations}
    run.max_tokens, run.max_invocations = max_tokens, max_invocations
    _audit(
        session,
        run,
        user_id,
        "budget_adjusted",
        before,
        {"max_tokens": max_tokens, "max_invocations": max_invocations},
        reason,
    )
    await session.commit()


async def reconcile(session, project_id, run_id, invocation_id, user_id, actual_tokens, reason):
    run = await _locked_run(session, project_id, run_id, user_id, reason)
    if run.status not in {"paused", "failed", "cancelled"}:
        raise Conflict("Billing can be reconciled only while the run is stopped.")
    call = await session.scalar(
        select(InvocationRow)
        .where(InvocationRow.id == invocation_id, InvocationRow.run_id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if call is None:
        raise NotFound("Invocation not found.")
    if call.status != "billed_unknown":
        raise Conflict("Only billed_unknown calls can be reconciled.")
    if run.used_tokens + actual_tokens >= 2**31:
        raise BadRequest("Token total exceeds the supported accounting range.")
    before = {"status": call.status, "reserved_tokens": run.reserved_tokens, "used_tokens": run.used_tokens}
    run.reserved_tokens -= call.token_upper_bound
    run.used_tokens += actual_tokens
    call.status = "reconciled"
    call.response = {"usage": {"total_tokens": actual_tokens}}
    call.error = "Manually reconciled without a usable response; this invocation will not be resent."
    _audit(
        session,
        run,
        user_id,
        "billing_reconciled",
        before,
        {"invocation_id": call.id, "actual_tokens": actual_tokens, "status": call.status},
        reason,
    )
    await session.commit()


async def _locked_run(session, project_id, run_id, user_id, reason):
    await ProjectRepository(session).require_role(project_id, user_id, "owner")
    if not reason.strip():
        raise BadRequest("A reason and verification evidence are required.")
    locked = await session.execute(
        update(RunRow)
        .where(RunRow.id == run_id, RunRow.project_id == project_id)
        .values(invocation_count=RunRow.invocation_count)
    )
    if locked.rowcount != 1:
        raise NotFound("Run not found.")
    return await session.get(RunRow, run_id, populate_existing=True)


def _audit(session, run, user_id, action, before, after, reason):
    session.add(
        AuditRow(
            id=new_id("audit"),
            project_id=run.project_id,
            actor_id=user_id,
            target_id=run.id,
            action=action,
            before=before,
            after=after,
            reason=reason.strip(),
        )
    )
