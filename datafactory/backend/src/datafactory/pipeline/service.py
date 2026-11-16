"""The production loop as services the routes call.

A run is queued and executed by the worker, so the API returns immediately and the
caller watches progress. A dataset is the set of samples a run produced. Review
records a human decision over a sample. Release freezes the samples that pass the
gates.
"""

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from datafactory.core.errors import BadRequest, Conflict, Forbidden, NotFound
from datafactory.core.execution import BilledUnknown, BudgetExceeded, RunInterrupted
from datafactory.core.idempotency import request_hash
from datafactory.core.ids import new_id
from datafactory.engine.columns import ColumnContext
from datafactory.engine.model_client import ModelClient
from datafactory.engine.recipe import Recipe
from datafactory.engine.recipes import RecipeRepository
from datafactory.pipeline.run import produce, release_check
from datafactory.store.projects import ProjectRepository
from datafactory.store.runs import RunStore
from datafactory.store.snapshots import SnapshotRepository
from datafactory.store.tables import (
    DatasetRow,
    IdempotencyRow,
    InvocationRow,
    RecipeRow,
    RecipeVersionRow,
    ReleaseRow,
    ReviewRow,
    RunCheckpointRow,
    RunRow,
    SampleRow,
)


class RunRecord(BaseModel):
    """A run as returned to clients."""

    id: str
    project_id: str
    recipe_id: str
    snapshot_id: str
    status: str
    sample_count: int
    limit: int = 0
    error: str = ""
    recipe_version_id: str
    mode: str
    seed: int
    batch_size: int
    attempt_generation: int
    completed_units: int
    total_units: int
    max_invocations: int
    max_tokens: int
    reserved_tokens: int
    used_tokens: int
    invocation_count: int
    preview: list[dict]


class CheckpointRecord(BaseModel):
    stage: int
    batches: int
    column: str
    rows: int
    elapsed_ms: int
    attempt_generation: int


class InvocationRecord(BaseModel):
    id: str
    column: str
    row_key: str
    model_id: str
    model_fingerprint: str
    status: str
    token_upper_bound: int
    usage: dict
    latency_ms: int
    error: str


class RunMetrics(BaseModel):
    run: RunRecord
    checkpoints: list[CheckpointRecord]
    invocations: list[InvocationRecord]
    next_invocation_cursor: str | None = None


class SampleRecord(BaseModel):
    """One produced sample."""

    id: str
    dataset_id: str
    query: str
    positives: list[str]
    negatives: list[str]
    split: str
    modality: str
    review_status: str
    body: dict = {}


class DatasetRecord(BaseModel):
    """A dataset summary."""

    id: str
    project_id: str
    run_id: str
    name: str
    sample_count: int


class OverviewRecord(BaseModel):
    datasets: int
    samples: int
    pending_reviews: int
    running: int
    releases: int


class GateRecord(BaseModel):
    name: str
    level: str
    passed: bool
    detail: str


class ReleaseRecord(BaseModel):
    """An immutable release."""

    id: str
    dataset_id: str
    status: str
    sample_count: int
    gates: list[GateRecord]


class ProductionService:
    """Runs, datasets, reviews and releases for one session."""

    def __init__(self, session, gateway, objects=None) -> None:
        self._session = session
        self._gateway = gateway
        self._objects = objects

    async def start_run(
        self,
        project_id: str,
        user_id: str,
        recipe_id: str,
        snapshot_id: str,
        limit: int,
        *,
        mode: str = "run",
        version_id: str | None = None,
        key: str = "",
    ) -> RunRecord:
        """Freeze a recipe and queue either a preview or a production run."""
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        scope = f"run:{project_id}:{user_id}"
        key_hash = request_hash({"key": key})
        payload_hash = request_hash(
            dict(recipe=recipe_id, snapshot=snapshot_id, limit=limit, mode=mode, version=version_id)
        )
        if key:
            replay = await self._replay_run(scope, key_hash, payload_hash, project_id)
            if replay:
                return replay
        recipe_row = await self._recipe(project_id, recipe_id)
        snapshot = await SnapshotRepository(self._session).require_project(snapshot_id, project_id)
        if snapshot.status != "ready":
            raise Conflict(f"Snapshot {snapshot_id} is {snapshot.status}.", code="snapshot_not_ready")
        if mode not in {"run", "preview"} or not 1 <= limit <= (50 if mode == "preview" else 500_000):
            raise BadRequest("Invalid run mode or seed limit.")
        if version_id:
            version = await self._session.get(RecipeVersionRow, version_id)
            if version is None or version.recipe_id != recipe_id:
                raise NotFound("Recipe version does not belong to this recipe.")
        else:
            version = await RecipeRepository(self._session).freeze(project_id, recipe_id)
        recipe = Recipe.model_validate(version.config)
        if recipe.seed.type != "ragflow_snapshot" or recipe.seed.unit != "segment":
            raise BadRequest("This seed reader is not implemented.", code="unsupported_seed")
        if recipe.task_type != "retrieval":
            raise BadRequest("This task view is not implemented.", code="unsupported_task")
        if recipe.seed.snapshot_id and recipe.seed.snapshot_id != snapshot_id:
            raise BadRequest("The selected snapshot differs from the frozen recipe seed.", code="snapshot_mismatch")
        run = RunRow(
            id=new_id("run"),
            project_id=project_id,
            recipe_id=recipe_row.id,
            recipe_version_id=version.id,
            snapshot_id=snapshot_id,
            status="queued",
            sample_count=0,
            limit_n=limit,
            user_id=user_id,
            mode=mode,
            seed=recipe.run.get("seed", 1),
            batch_size=recipe.run.get("batch_size", 64),
            max_invocations=recipe.budget.get("max_invocations", 1000),
            max_tokens=recipe.budget.get("max_tokens", 1_000_000),
        )
        self._session.add(run)
        if key:
            self._session.add(
                IdempotencyRow(scope=scope, key_hash=key_hash, request_hash=payload_hash, resource_id=run.id)
            )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if key:
                replay = await self._replay_run(scope, key_hash, payload_hash, project_id)
                if replay:
                    return replay
            raise
        return self._run(run)

    async def _replay_run(self, scope, key_hash, payload_hash, project_id):
        prior = await self._session.get(IdempotencyRow, (scope, key_hash))
        if prior is None:
            return None
        if prior.request_hash != payload_hash:
            raise Conflict("Idempotency key was already used for a different request.")
        return self._run(await self._run_row(project_id, prior.resource_id))

    async def execute_run(self, run_id: str, generation: int) -> RunRecord:
        run = await self._session.get(RunRow, run_id)
        if run is None:
            raise NotFound(f"No run {run_id}.", code="run_not_found")
        if run.status != "running" or run.attempt_generation != generation:
            return self._run(run)
        store = RunStore(self._session, self._objects, run_id, generation)
        recipe = None
        try:
            await store.check()
            await ProjectRepository(self._session).require_role(run.project_id, run.user_id, "editor")
            version = await self._session.get(RecipeVersionRow, run.recipe_version_id)
            if version is None or version.recipe_id != run.recipe_id:
                raise ValueError("Run has no valid frozen recipe version.")
            recipe = Recipe.model_validate(version.config)
            snapshots = SnapshotRepository(self._session)
            await snapshots.require_project(run.snapshot_id, run.project_id)
            families = {doc.doc_id: doc.family_id for doc in await snapshots.documents(run.snapshot_id)}
            segments = []
            cursor = None
            while True:
                page = await snapshots.segments(run.snapshot_id, limit=1000, after_id=cursor)
                if not page:
                    break
                segments.extend(
                    {**segment.model_dump(), "family_id": families.get(segment.origin.doc_id)} for segment in page
                )
                cursor = page[-1].id
            await self._session.commit()
            samples = await produce(
                recipe,
                segments,
                ColumnContext(self._gateway, ModelClient(self._gateway, store)),
                seed=run.seed,
                limit=run.limit_n,
                checkpoints=store,
            )
            await store.fence()
            if run.mode == "run":
                dataset = DatasetRow(
                    id=new_id("dataset"),
                    project_id=run.project_id,
                    run_id=run.id,
                    name=f"{run.recipe_id} / {run.recipe_version_id}",
                    sample_count=len(samples),
                )
                self._session.add(dataset)
                for sample in samples:
                    sample["lineage"] = {
                        "run_id": run.id,
                        "snapshot_id": run.snapshot_id,
                        "recipe_version_id": run.recipe_version_id,
                    }
                    self._session.add(
                        SampleRow(
                            id=new_id("sample"),
                            dataset_id=dataset.id,
                            query=str(sample["query"] or ""),
                            positives=sample["positives"],
                            negatives=sample["negatives"],
                            split=sample["split"],
                            modality=sample["modality"],
                            review_status="pending",
                            body=sample,
                        )
                    )
            await self._session.execute(
                update(RunRow)
                .where(RunRow.id == run_id)
                .values(
                    sample_count=len(samples),
                    status="completed",
                    lease_until=None,
                    preview=samples if run.mode == "preview" else [],
                    error="",
                )
            )
            await self._session.commit()
        except RunInterrupted:
            await self._session.rollback()
        except Exception as exc:
            await self._session.rollback()
            status = "failed"
            if isinstance(exc, BilledUnknown):
                status = "paused"
            elif isinstance(exc, BudgetExceeded):
                status = "failed" if recipe and recipe.budget.get("on_exceed") == "fail" else "paused"
            elif isinstance(exc, Forbidden):
                status = "blocked"
            await self._session.execute(
                update(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.status == "running",
                    RunRow.attempt_generation == generation,
                )
                .values(status=status, error=str(exc)[:2000], lease_until=None, attempt_generation=generation + 1)
            )
            await self._session.commit()
        await self._session.refresh(run)
        return self._run(run)

    async def control_run(self, project_id: str, run_id: str, user_id: str, action: str) -> RunRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        run = await self._run_row(project_id, run_id)
        allowed, target = {
            "pause": (("queued", "running"), "paused"),
            "resume": (("paused", "blocked"), "queued"),
            "cancel": (("queued", "running", "paused", "blocked"), "cancelled"),
        }[action]
        if action == "resume":
            uncertain = await self._session.scalar(
                select(InvocationRow.id)
                .where(
                    InvocationRow.run_id == run_id,
                    InvocationRow.status.in_(("sent", "billed_unknown")),
                )
                .limit(1)
            )
            if uncertain:
                raise Conflict(
                    f"Invocation {uncertain} has an uncertain outcome; automatic replay is disabled.",
                    code="billed_unknown",
                )
        changed = await self._session.execute(
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status.in_(allowed),
                RunRow.attempt_generation == run.attempt_generation,
            )
            .values(status=target, lease_until=None, attempt_generation=RunRow.attempt_generation + 1)
        )
        if changed.rowcount != 1:
            await self._session.rollback()
            raise Conflict("Run state changed or this transition is not allowed.", code="run_transition")
        await self._session.commit()
        await self._session.refresh(run)
        return self._run(run)

    async def get_run(self, project_id: str, run_id: str, user_id: str) -> RunRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        return self._run(await self._run_row(project_id, run_id))

    async def metrics(self, project_id, run_id, user_id, after=None) -> RunMetrics:
        run = await self.get_run(project_id, run_id, user_id)
        checkpoints = (
            await self._session.execute(
                select(
                    RunCheckpointRow.stage,
                    RunCheckpointRow.column_name,
                    func.count().label("batches"),
                    func.sum(RunCheckpointRow.row_count).label("rows"),
                    func.sum(RunCheckpointRow.elapsed_ms).label("elapsed_ms"),
                    func.max(RunCheckpointRow.attempt_generation).label("attempt_generation"),
                )
                .where(RunCheckpointRow.run_id == run_id)
                .group_by(RunCheckpointRow.stage, RunCheckpointRow.column_name)
                .order_by(RunCheckpointRow.stage)
            )
        ).all()
        query = select(InvocationRow).where(InvocationRow.run_id == run_id).order_by(InvocationRow.id).limit(101)
        if after:
            query = query.where(InvocationRow.id > after)
        records = list((await self._session.scalars(query)).all())
        return RunMetrics(
            run=run,
            checkpoints=[
                CheckpointRecord(
                    stage=c.stage,
                    batches=c.batches,
                    column=c.column_name,
                    rows=c.rows,
                    elapsed_ms=c.elapsed_ms,
                    attempt_generation=c.attempt_generation,
                )
                for c in checkpoints
            ],
            invocations=[
                InvocationRecord(
                    id=r.id,
                    column=r.column_name,
                    row_key=r.row_key,
                    model_id=r.model_id,
                    model_fingerprint=r.model_fingerprint,
                    status=r.status,
                    token_upper_bound=r.token_upper_bound,
                    usage=r.response.get("usage", {}),
                    latency_ms=r.response.get("latency_ms", 0),
                    error=r.error,
                )
                for r in records[:100]
            ],
            next_invocation_cursor=records[99].id if len(records) > 100 else None,
        )

    async def list_runs(self, project_id: str, user_id: str) -> list[RunRecord]:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        rows = (
            await self._session.scalars(
                select(RunRow).where(RunRow.project_id == project_id).order_by(RunRow.id.desc()).limit(200)
            )
        ).all()
        return [self._run(row) for row in rows]

    async def list_datasets(self, project_id: str, user_id: str) -> list[DatasetRecord]:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        rows = (await self._session.scalars(select(DatasetRow).where(DatasetRow.project_id == project_id))).all()
        return [
            DatasetRecord(
                id=row.id, project_id=row.project_id, run_id=row.run_id, name=row.name, sample_count=row.sample_count
            )
            for row in rows
        ]

    async def samples(self, project_id: str, dataset_id: str, user_id: str, split: str | None) -> list[SampleRecord]:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        dataset = await self._dataset(project_id, dataset_id)
        rows = (await self._session.scalars(select(SampleRow).where(SampleRow.dataset_id == dataset.id))).all()
        return [self._sample(row) for row in rows if split is None or row.split == split]

    async def review_queue(self, project_id: str, user_id: str) -> list[SampleRecord]:
        """Pending samples across the project's datasets, oldest dataset first."""
        await ProjectRepository(self._session).require_role(project_id, user_id, "reviewer")
        datasets = (await self._session.scalars(select(DatasetRow.id).where(DatasetRow.project_id == project_id))).all()
        if not datasets:
            return []
        rows = (
            await self._session.scalars(
                select(SampleRow)
                .where(SampleRow.dataset_id.in_(datasets), SampleRow.review_status == "pending")
                .limit(200)
            )
        ).all()
        return [self._sample(row) for row in rows]

    async def review(self, project_id: str, sample_id: str, user_id: str, decision: str, reason: str) -> SampleRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "reviewer")
        if decision not in ("approved", "rejected"):
            raise BadRequest("A review decision is approved or rejected.", code="bad_decision")
        row = await self._session.get(SampleRow, sample_id)
        if row is None:
            raise NotFound(f"No sample {sample_id}.", code="sample_not_found")
        await self._dataset(project_id, row.dataset_id)
        row.review_status = decision
        self._session.add(
            ReviewRow(id=new_id("review"), sample_id=sample_id, reviewer_id=user_id, decision=decision, reason=reason)
        )
        await self._session.commit()
        return self._sample(row)

    async def counts(self, project_id: str, user_id: str) -> dict:
        """The numbers the overview and the sidebar badge show."""
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        datasets = (await self._session.scalars(select(DatasetRow).where(DatasetRow.project_id == project_id))).all()
        dataset_ids = [row.id for row in datasets]
        pending = 0
        if dataset_ids:
            pending = await self._session.scalar(
                select(func.count())
                .select_from(SampleRow)
                .where(SampleRow.dataset_id.in_(dataset_ids), SampleRow.review_status == "pending")
            )
        running = await self._session.scalar(
            select(func.count())
            .select_from(RunRow)
            .where(RunRow.project_id == project_id, RunRow.status.in_(("queued", "running")))
        )
        released = await self._session.scalar(
            select(func.count())
            .select_from(ReleaseRow)
            .where(ReleaseRow.dataset_id.in_(dataset_ids or [""]), ReleaseRow.status == "released")
        )
        return {
            "datasets": len(datasets),
            "samples": sum(row.sample_count for row in datasets),
            "pending_reviews": pending or 0,
            "running": running or 0,
            "releases": released or 0,
        }

    async def release(self, project_id: str, dataset_id: str, user_id: str) -> ReleaseRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        dataset = await self._dataset(project_id, dataset_id)
        rows = (await self._session.scalars(select(SampleRow).where(SampleRow.dataset_id == dataset.id))).all()
        approved = [row.body for row in rows if row.review_status == "approved"]
        if not approved:
            raise Conflict("A release needs at least one approved sample.", code="nothing_approved")
        run = await self._run_row(project_id, dataset.run_id)
        snapshot = await SnapshotRepository(self._session).require_project(run.snapshot_id, project_id)
        gates = release_check(approved, snapshot.status)
        blocked = [gate for gate in gates if gate["level"] == "blocker" and not gate["passed"]]
        record = ReleaseRow(
            id=new_id("release"),
            dataset_id=dataset.id,
            status="blocked" if blocked else "released",
            sample_count=len(approved),
            gates=gates,
            samples=approved,
        )
        self._session.add(record)
        await self._session.commit()
        return ReleaseRecord(
            id=record.id,
            dataset_id=dataset.id,
            status=record.status,
            sample_count=record.sample_count,
            gates=[GateRecord.model_validate(gate) for gate in gates],
        )

    async def list_releases(self, project_id: str, user_id: str) -> list[ReleaseRecord]:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        datasets = (await self._session.scalars(select(DatasetRow.id).where(DatasetRow.project_id == project_id))).all()
        if not datasets:
            return []
        rows = (await self._session.scalars(select(ReleaseRow).where(ReleaseRow.dataset_id.in_(datasets)))).all()
        return [
            ReleaseRecord(
                id=row.id, dataset_id=row.dataset_id, status=row.status, sample_count=row.sample_count, gates=row.gates
            )
            for row in rows
        ]

    async def export(self, project_id: str, release_id: str, user_id: str, adapter: str) -> dict:
        """Render a release through one adapter. Bytes are not written to disk."""
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        row = await self._session.get(ReleaseRow, release_id)
        if row is None or row.status != "released":
            raise Conflict("Only a released dataset can be exported.", code="release_not_exportable")
        await self._dataset(project_id, row.dataset_id)
        from datafactory.adapters import (
            AdapterError,
            ReleaseCorpus,
            ReleaseSample,
            export_beir,
            export_canonical,
            export_flagembedding,
            export_sentence_transformers,
        )

        samples = [
            ReleaseSample(
                query_id=item.get("row_key", ""),
                query=item.get("query") or "",
                split=item.get("split", "train"),
                positives=item.get("positives", []),
                negatives=item.get("negatives", []),
                modality=item.get("modality", "text"),
                positive_scores=[item["teacher_scores"]["scores"][sid] for sid in item.get("positives", [])]
                if all(sid in (item.get("teacher_scores") or {}).get("scores", {}) for sid in item.get("positives", []))
                else [],
                negative_scores=[item["teacher_scores"]["scores"][sid] for sid in item.get("negatives", [])]
                if all(sid in (item.get("teacher_scores") or {}).get("scores", {}) for sid in item.get("negatives", []))
                else [],
            )
            for item in row.samples
        ]
        dataset = await self._dataset(project_id, row.dataset_id)
        run = await self._run_row(project_id, dataset.run_id)
        repository = SnapshotRepository(self._session)
        await repository.require_project(run.snapshot_id, project_id)
        segments = []
        cursor = None
        while True:
            page = await repository.segments(run.snapshot_id, limit=1000, after_id=cursor)
            segments.extend(page)
            if len(page) < 1000:
                break
            cursor = page[-1].id
        corpus = ReleaseCorpus(
            segments={segment.id: "\n".join(part.text or "" for part in segment.parts) for segment in segments},
            modalities={segment.id: segment.modality for segment in segments},
        )
        exporters = {
            "canonical": export_canonical,
            "beir": export_beir,
            "sentence_transformers": export_sentence_transformers,
            "flagembedding": export_flagembedding,
        }
        if adapter not in exporters:
            raise BadRequest(f"No adapter {adapter}.", code="unknown_adapter")
        missing = sorted(
            {sid for sample in samples for sid in sample.positives + sample.negatives} - corpus.segments.keys()
        )
        if missing:
            raise Conflict(f"Release refers to missing segments: {', '.join(missing)}.", code="release_incomplete")
        try:
            result = exporters[adapter](samples, corpus)
        except AdapterError as exc:
            raise BadRequest("; ".join(issue.message for issue in exc.issues), code="adapter_incompatible") from exc
        return {"adapter": adapter, "files": result.files, "issues": [issue.message for issue in result.issues]}

    async def get_release(self, project_id: str, release_id: str, user_id: str) -> ReleaseRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        row = await self._session.get(ReleaseRow, release_id)
        if row is None:
            raise NotFound(f"No release {release_id}.", code="release_not_found")
        await self._dataset(project_id, row.dataset_id)
        return ReleaseRecord(
            id=row.id, dataset_id=row.dataset_id, status=row.status, sample_count=row.sample_count, gates=row.gates
        )

    async def _recipe(self, project_id: str, recipe_id: str) -> RecipeRow:
        row = await self._session.get(RecipeRow, recipe_id)
        if row is None or row.project_id != project_id:
            raise NotFound(f"No recipe {recipe_id}.", code="recipe_not_found")
        return row

    async def _run_row(self, project_id: str, run_id: str) -> RunRow:
        row = await self._session.get(RunRow, run_id)
        if row is None or row.project_id != project_id:
            raise NotFound(f"No run {run_id}.", code="run_not_found")
        return row

    async def _dataset(self, project_id: str, dataset_id: str) -> DatasetRow:
        row = await self._session.get(DatasetRow, dataset_id)
        if row is None or row.project_id != project_id:
            raise NotFound(f"No dataset {dataset_id}.", code="dataset_not_found")
        return row

    def _run(self, row: RunRow) -> RunRecord:
        return RunRecord(
            id=row.id,
            project_id=row.project_id,
            recipe_id=row.recipe_id,
            snapshot_id=row.snapshot_id,
            status=row.status,
            sample_count=row.sample_count,
            limit=row.limit_n,
            error=row.error,
            **{
                field: getattr(row, field)
                for field in (
                    "recipe_version_id",
                    "mode",
                    "seed",
                    "batch_size",
                    "attempt_generation",
                    "completed_units",
                    "total_units",
                    "max_invocations",
                    "max_tokens",
                    "reserved_tokens",
                    "used_tokens",
                    "invocation_count",
                    "preview",
                )
            },
        )

    def _sample(self, row: SampleRow) -> SampleRecord:
        return SampleRecord(
            id=row.id,
            dataset_id=row.dataset_id,
            query=row.query,
            positives=row.positives,
            negatives=row.negatives,
            split=row.split,
            modality=row.modality,
            review_status=row.review_status,
            body=row.body or {},
        )
