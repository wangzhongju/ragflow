"""The sole model invocation path, with reservations and replay-safe accounting."""

import hashlib
import json
from typing import Protocol

import httpx
from sqlalchemy import select, update

from datafactory.core.errors import GatewayUnavailable
from datafactory.core.execution import BilledUnknown, BudgetExceeded
from datafactory.core.ids import new_id
from datafactory.gateway.dto import Invocation
from datafactory.store.runs import RunStore
from datafactory.store.tables import InvocationRow, RunRow


class ModelInvoker(Protocol):
    async def invoke(
        self,
        model_id: str,
        op: str,
        inputs: dict,
        gen_conf: dict | None = None,
        *,
        column: str,
        row_key: str,
    ) -> Invocation: ...


class ModelClient:
    def __init__(self, gateway, store: RunStore):
        self._gateway = gateway
        self._store = store

    async def invoke(
        self,
        model_id: str,
        op: str,
        inputs: dict,
        gen_conf: dict | None = None,
        *,
        column: str,
        row_key: str,
    ) -> Invocation:
        gen_conf = dict(gen_conf or {})
        if op == "chat":
            gen_conf.setdefault("max_tokens", 2048)
        request = {"model_id": model_id, "op": op, "inputs": inputs, "gen_conf": gen_conf}
        encoded = json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        call_key = hashlib.sha256(json.dumps([column, row_key, digest]).encode()).hexdigest()
        store = self._store
        session = store.session
        await store.fence()
        previous = await session.scalar(
            select(InvocationRow).where(
                InvocationRow.run_id == store.run_id,
                InvocationRow.call_key == call_key,
            )
        )
        if previous:
            await session.commit()
            if previous.status == "succeeded":
                return Invocation.model_validate(previous.response)
            if previous.status in {"sent", "billed_unknown"}:
                raise BilledUnknown(f"Invocation {previous.id} has an uncertain outcome; it will not be sent again.")
            raise RuntimeError(previous.error)
        # UTF-8 byte count bounds text tokens; this executor accepts text model inputs.
        if inputs.get("images"):
            raise ValueError("Image model calls require the asset assembly engine.")
        upper = len(encoded) + int(gen_conf.get("max_tokens", 0))
        if op == "rerank":
            upper += len(str(inputs.get("query", "")).encode()) * max(0, len(inputs.get("texts", [])) - 1)
        if upper <= 0 or int(gen_conf.get("max_tokens", 1)) <= 0:
            raise ValueError("Token bounds must be positive.")
        reserved = await session.execute(
            update(RunRow)
            .where(
                RunRow.id == store.run_id,
                RunRow.invocation_count < RunRow.max_invocations,
                RunRow.used_tokens + RunRow.reserved_tokens + upper <= RunRow.max_tokens,
            )
            .values(invocation_count=RunRow.invocation_count + 1, reserved_tokens=RunRow.reserved_tokens + upper)
        )
        if reserved.rowcount != 1:
            await session.rollback()
            raise BudgetExceeded("Model call exceeds the run's invocation or token budget.")
        record = InvocationRow(
            id=new_id("invocation"),
            run_id=store.run_id,
            call_key=call_key,
            column_name=column,
            row_key=row_key,
            model_id=model_id,
            attempt_generation=store.generation,
            status="sent",
            token_upper_bound=upper,
            request_digest=digest,
            request={"model_id": model_id, "op": op, "input_bytes": len(encoded), "gen_conf": gen_conf},
        )
        session.add(record)
        await session.commit()
        try:
            result = await self._gateway.invoke(model_id, op, inputs, gen_conf)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            await self._settle(record, "rejected", error=str(exc))
            raise
        except GatewayUnavailable as exc:
            if exc.gateway_code in {400, 401, 403, 404, 429, 108}:
                await self._settle(record, "rejected", error=str(exc))
                raise
            await self._settle(record, "billed_unknown", error=str(exc))
            raise BilledUnknown(f"Invocation {record.id}: {exc}") from exc
        except Exception as exc:
            await self._settle(record, "billed_unknown", error=str(exc))
            raise BilledUnknown(f"Invocation {record.id}: {exc}") from exc
        await self._settle(record, "succeeded", result=result)
        return result

    async def _settle(self, record, status, *, result=None, error=""):
        session = self._store.session
        # Settlement survives a pause/cancel: the provider may already have billed it.
        # Claim, reservation and settlement lock the run before its invocation rows.
        await session.execute(
            update(RunRow).where(RunRow.id == record.run_id).values(invocation_count=RunRow.invocation_count)
        )
        values = {"status": status, "error": error[:2000]}
        if result is not None:
            values.update(response=result.model_dump(), model_fingerprint=result.model_fingerprint)
        payable = ("sent", "billed_unknown") if result is not None else ("sent",)
        settled = await session.execute(
            update(InvocationRow)
            .where(
                InvocationRow.id == record.id,
                InvocationRow.status.in_(payable),
            )
            .values(**values)
        )
        if settled.rowcount == 1 and status != "billed_unknown":
            # A response without usage does not prove zero cost. Retain its reservation.
            actual = max(0, result.usage.total_tokens) if result is not None else 0
            if result is not None and actual == 0:
                await session.commit()
                return
            await session.execute(
                update(RunRow)
                .where(RunRow.id == record.run_id)
                .values(
                    reserved_tokens=RunRow.reserved_tokens - record.token_upper_bound,
                    used_tokens=RunRow.used_tokens + actual,
                )
            )
        await session.commit()
