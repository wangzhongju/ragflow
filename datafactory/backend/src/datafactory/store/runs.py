"""Run ownership and immutable, content-verified Parquet checkpoints."""

import asyncio
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import update

from datafactory.core.execution import RunInterrupted
from datafactory.store.tables import RunCheckpointRow, RunRow


def lease_deadline():
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)


class RunStore:
    def __init__(self, session, objects, run_id: str, generation: int):
        self.session = session
        self.objects = objects
        self.run_id = run_id
        self.generation = generation

    async def fence(self):
        """Lock and renew the attempt in the caller's transaction."""
        claimed = await self.session.execute(
            update(RunRow)
            .where(
                RunRow.id == self.run_id,
                RunRow.status == "running",
                RunRow.attempt_generation == self.generation,
            )
            .values(lease_until=lease_deadline())
        )
        if claimed.rowcount != 1:
            await self.session.rollback()
            raise RunInterrupted("Run was paused, cancelled or claimed by a newer worker.")

    async def check(self):
        await self.fence()
        await self.session.commit()

    async def load(self, stage: int, batch: int) -> list[dict] | None:
        await self.check()
        checkpoint = await self.session.get(RunCheckpointRow, (self.run_id, stage, batch))
        if checkpoint is None:
            return None
        key = checkpoint.object_key
        await self.session.commit()
        data, _ = await asyncio.to_thread(self.objects.get_object, key)
        if hashlib.sha256(data).hexdigest() != key.rsplit("/", 1)[-1].removesuffix(".parquet"):
            raise ValueError("Checkpoint content hash does not match.")
        return await asyncio.to_thread(_decode, data)

    async def save(self, stage: int, batch: int, column: str, rows: list[dict], elapsed_ms: int):
        data = await asyncio.to_thread(_encode, rows)
        digest = hashlib.sha256(data).hexdigest()
        key = f"runs/{self.run_id}/batches/{stage}/{batch}/{self.generation}/{digest}.parquet"
        await asyncio.to_thread(self.objects.put_object, key, data, "application/vnd.apache.parquet")
        await self.fence()
        self.session.add(
            RunCheckpointRow(
                run_id=self.run_id,
                stage=stage,
                batch=batch,
                attempt_generation=self.generation,
                column_name=column,
                object_key=key,
                row_count=len(rows),
                elapsed_ms=elapsed_ms,
            )
        )
        await self.session.execute(
            update(RunRow).where(RunRow.id == self.run_id).values(completed_units=RunRow.completed_units + 1)
        )
        await self.session.commit()

    async def plan(self, units: int):
        await self.fence()
        await self.session.execute(update(RunRow).where(RunRow.id == self.run_id).values(total_units=units))
        await self.session.commit()


def _encode(rows):
    # JSON preserves heterogeneous user-defined column types without schema inference loss.
    values = [json.dumps({k: v for k, v in row.items() if k != "_corpus"}, ensure_ascii=False) for row in rows]
    table = pa.table({"row": pa.array(values, type=pa.string())})
    output = io.BytesIO()
    pq.write_table(table, output, compression="zstd")
    return output.getvalue()


def _decode(data):
    return [json.loads(value) for value in pq.read_table(io.BytesIO(data)).column("row").to_pylist()]
