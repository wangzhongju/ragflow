"""Persistence for frozen snapshots.

Segments are inserted once per origin chunk. A second build of the same sources
adds nothing, which is what makes snapshot creation safe to retry.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datafactory.core.errors import Conflict, NotFound
from datafactory.core.ids import new_id
from datafactory.domain.content import (
    ContentPart,
    HealthReport,
    Position,
    Segment,
    SegmentOrigin,
    SourceDocument,
)
from datafactory.domain.snapshot import SnapshotDraft
from datafactory.store.objects import ObjectStore
from datafactory.store.tables import AssetRow, SegmentRow, SnapshotAssetRow, SnapshotRow, SourceDocumentRow


class SnapshotRecord:
    """A snapshot as the rest of the platform sees it."""

    def __init__(self, row: SnapshotRow) -> None:
        self.id = row.id
        self.project_id = row.project_id
        self.name = row.name
        self.status = row.status
        self.sources = row.sources
        self.vector_profile = row.vector_profile
        self.stats = row.stats
        self.created_by = row.created_by


class SnapshotRepository:
    """Reads and writes snapshots for one database session."""

    def __init__(self, session: AsyncSession, objects: ObjectStore | None = None) -> None:
        self._session = session
        self._objects = objects

    async def create(self, project_id: str, user_id: str, name: str, sources: list[dict]) -> SnapshotRecord:
        """Open a snapshot in the ``building`` state. The build fills it in."""
        row = SnapshotRow(
            id=new_id("snapshot"),
            project_id=project_id,
            name=name,
            status="building",
            sources=sources,
            vector_profile=[],
            stats={},
            created_by=user_id,
        )
        self._session.add(row)
        await self._session.commit()
        return SnapshotRecord(row)

    async def save_build(self, snapshot_id: str, draft: SnapshotDraft) -> SnapshotRecord:
        """Persist a finished build and mark the snapshot ready.

        Segments already stored for the same origin chunk are kept as they are,
        so rebuilding is idempotent. Assets are stored once per content hash.
        """
        row = await self._require(snapshot_id)
        if row.status in {"ready", "stale"}:
            return SnapshotRecord(row)
        if row.status != "building":
            raise Conflict("Only building snapshots can accept content.")
        existing = set(
            await self._session.scalars(select(SegmentRow.origin_chunk_id).where(SegmentRow.snapshot_id == snapshot_id))
        )
        for segment in draft.segments:
            if segment.origin.chunk_id in existing:
                continue
            self._session.add(_segment_row(segment))
        known_assets = set(await self._session.scalars(select(AssetRow.asset_id)))
        for asset in draft.assets:
            if asset.asset_id in known_assets:
                continue
            if self._objects is None:
                raise RuntimeError("Snapshot assets require a configured object store.")
            uri = await asyncio.to_thread(self._objects.put_asset, asset.asset_id, asset.data, asset.mime)
            self._session.add(AssetRow(asset_id=asset.asset_id, mime=asset.mime, size=len(asset.data), storage_uri=uri))
            known_assets.add(asset.asset_id)
        known_docs = set(
            await self._session.scalars(
                select(SourceDocumentRow.doc_id).where(SourceDocumentRow.snapshot_id == snapshot_id)
            )
        )
        linked = set(
            await self._session.scalars(
                select(SnapshotAssetRow.asset_id).where(SnapshotAssetRow.snapshot_id == snapshot_id)
            )
        )
        referenced = {part.asset_id for segment in draft.segments for part in segment.parts if part.asset_id}
        if referenced - known_assets:
            raise ValueError("Snapshot references assets without frozen bytes.")
        for asset_id in referenced - linked:
            self._session.add(SnapshotAssetRow(asset_id=asset_id, snapshot_id=snapshot_id))
        for document in draft.documents:
            if document.doc_id in known_docs:
                continue
            self._session.add(_document_row(document))
        row.vector_profile = draft.vector_profile
        if draft.health is None:
            raise ValueError("Snapshot build must include a health report.")
        row.stats = draft.health.model_dump()
        row.status = "ready"
        row.frozen_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.commit()
        return SnapshotRecord(row)

    async def mark_failed(self, snapshot_id: str, reason: str) -> None:
        """Record that a build stopped. The partial rows stay for inspection."""
        row = await self._require(snapshot_id)
        row.status = "failed"
        row.stats = {**row.stats, "error": reason}
        await self._session.commit()

    async def get(self, snapshot_id: str) -> SnapshotRecord:
        """One snapshot, or not found."""
        return SnapshotRecord(await self._require(snapshot_id))

    async def require_project(self, snapshot_id: str, project_id: str) -> SnapshotRecord:
        """Resolve a snapshot within its owning project, without disclosing foreign resources."""
        record = await self.get(snapshot_id)
        if record.project_id != project_id:
            raise NotFound("Snapshot not found in this project.", code="snapshot_not_found")
        return record

    async def list_for_project(self, project_id: str) -> list[SnapshotRecord]:
        """A project's snapshots, newest first."""
        rows = await self._session.scalars(
            select(SnapshotRow).where(SnapshotRow.project_id == project_id).order_by(SnapshotRow.created_at.desc())
        )
        return [SnapshotRecord(row) for row in rows]

    async def segments(self, snapshot_id: str, limit: int = 50, after_id: str | None = None) -> list[Segment]:
        """One cursor page of segments, ordered by their platform id."""
        query = select(SegmentRow).where(SegmentRow.snapshot_id == snapshot_id).order_by(SegmentRow.id).limit(limit)
        if after_id:
            query = query.where(SegmentRow.id > after_id)
        return [_segment(row) for row in await self._session.scalars(query)]

    async def health(self, snapshot_id: str) -> HealthReport:
        """The corpus check stored with the snapshot."""
        row = await self._require(snapshot_id)
        fields = set(HealthReport.model_fields)
        return HealthReport.model_validate({key: value for key, value in row.stats.items() if key in fields})

    async def documents(self, snapshot_id: str) -> list[SourceDocument]:
        """The source documents and the family each one was clustered into."""
        rows = await self._session.scalars(
            select(SourceDocumentRow).where(SourceDocumentRow.snapshot_id == snapshot_id)
        )
        return [
            SourceDocument(
                id=row.id,
                snapshot_id=row.snapshot_id,
                kb_id=row.kb_id,
                doc_id=row.doc_id,
                name=row.name,
                suffix=row.suffix,
                content_hash=row.content_hash,
                chunk_count=row.chunk_count,
                family_id=row.family_id,
            )
            for row in rows
        ]

    async def mark_stale(self, snapshot_id: str, drifted: list[str]) -> SnapshotRecord:
        """Flag a snapshot whose source documents have changed. Nothing is rewritten."""
        row = await self._require(snapshot_id)
        if drifted:
            row.status = "stale"
            row.stats = {**row.stats, "drifted_documents": drifted}
            await self._session.commit()
        return SnapshotRecord(row)

    async def _require(self, snapshot_id: str) -> SnapshotRow:
        row = await self._session.get(SnapshotRow, snapshot_id)
        if row is None:
            raise NotFound(f"Snapshot {snapshot_id} not found.")
        return row


def _segment_row(segment: Segment) -> SegmentRow:
    return SegmentRow(
        id=segment.id,
        snapshot_id=segment.snapshot_id,
        origin_kb_id=segment.origin.kb_id,
        origin_doc_id=segment.origin.doc_id,
        origin_chunk_id=segment.origin.chunk_id,
        modality=segment.modality,
        parts=[part.model_dump() for part in segment.parts],
        title=segment.title,
        position=segment.position.model_dump(),
        parent_segment_id=segment.parent_segment_id,
        content_hash=segment.hash,
        minhash=segment.minhash,
        tokens=segment.tokens,
        meta=segment.meta,
    )


def _segment(row: SegmentRow) -> Segment:
    return Segment(
        id=row.id,
        snapshot_id=row.snapshot_id,
        origin=SegmentOrigin(
            kb_id=row.origin_kb_id,
            doc_id=row.origin_doc_id,
            chunk_id=row.origin_chunk_id,
            content_hash=row.content_hash,
        ),
        modality=row.modality,  # type: ignore[arg-type]
        parts=[ContentPart.model_validate(part) for part in row.parts],
        title=row.title,
        position=Position.model_validate(row.position),
        parent_segment_id=row.parent_segment_id,
        hash=row.content_hash,
        minhash=row.minhash,
        tokens=row.tokens,
        meta=row.meta,
    )


def _document_row(document: SourceDocument) -> SourceDocumentRow:
    return SourceDocumentRow(
        id=document.id,
        snapshot_id=document.snapshot_id,
        kb_id=document.kb_id,
        doc_id=document.doc_id,
        name=document.name,
        suffix=document.suffix,
        content_hash=document.content_hash,
        chunk_count=document.chunk_count,
        family_id=document.family_id,
    )
