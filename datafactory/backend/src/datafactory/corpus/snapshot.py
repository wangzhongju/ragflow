"""Corpus snapshots: freezing RAGFlow chunks into segments.

A snapshot copies text and image bytes, never vectors. Rebuilding with the same
sources is idempotent: segments are keyed by their origin, assets by their
SHA-256. Chunks that are disabled, part of the table of contents, RAPTOR
summaries, or empty are counted and skipped.
"""

import asyncio
import hashlib

from datafactory.core.ids import new_id
from datafactory.domain.content import (
    ContentPart,
    HealthReport,
    Position,
    Segment,
    SegmentOrigin,
    SourceDocument,
)
from datafactory.domain.fingerprint import content_hash, garbage_ratio, jaccard, minhash_of, modality_of, tokens_of
from datafactory.domain.snapshot import FrozenAsset, SnapshotDraft
from datafactory.gateway.client import GatewayClient
from datafactory.gateway.dto import Chunk, Document

_SHORT = 20
_LONG = 2000
_NEAR_DUP = 0.8
_READY = ("DONE", "3")


class SnapshotBuilder:
    """Pulls documents from the gateway and freezes the ones that are ready."""

    def __init__(self, gateway: GatewayClient) -> None:
        self._gateway = gateway

    async def build(self, snapshot_id: str, sources: list[dict]) -> SnapshotDraft:
        """Freeze ``sources``. Each source is ``{kb_id, doc_ids?}``; no doc ids means all."""
        draft = SnapshotDraft()
        for source in sources:
            kb_id = source["kb_id"]
            wanted = set(source.get("doc_ids") or [])
            documents = await self._all_documents(kb_id)
            chosen = [doc for doc in documents if not wanted or doc.id in wanted]
            ready = [doc for doc in chosen if _is_ready(doc)]
            draft.not_ready.extend(doc.id for doc in chosen if not _is_ready(doc))
            profile = await self._profile(kb_id, ready)
            if profile:
                draft.vector_profile.append(profile)
            if ready:
                await self._freeze_documents(snapshot_id, kb_id, ready, draft)
        _link_parents(draft)
        await asyncio.to_thread(_finish_draft, draft)
        return draft

    async def _all_documents(self, kb_id: str) -> list[Document]:
        documents: list[Document] = []
        cursor: str | None = None
        while True:
            page = await self._gateway.list_documents(kb_id, cursor)
            documents.extend(page.documents)
            if not page.next_cursor:
                return documents
            cursor = page.next_cursor

    async def _profile(self, kb_id: str, documents: list[Document]) -> dict:
        datasets = {dataset.id: dataset for dataset in await self._gateway.list_datasets()}
        dataset = datasets.get(kb_id)
        if dataset is None:
            return {}
        return {
            "kb_id": kb_id,
            "embd_id": dataset.embd_id,
            "dim": dataset.vector_dim,
            "vector_semantics": {
                # The stored vector mixes the title in at this weight. RAGFlow
                # defaults it to 0.1 when the knowledge base leaves it unset.
                "title_weight": dataset.filename_embd_weight if dataset.filename_embd_weight is not None else 0.1,
                "question_substitution": False,
            },
            "document_count": len(documents),
        }

    async def _freeze_documents(
        self, snapshot_id: str, kb_id: str, documents: list[Document], draft: SnapshotDraft
    ) -> None:
        by_doc = {doc.id: doc for doc in documents}
        seen_origins: set[str] = set()
        async for chunk in self._gateway.scan_chunks(kb_id, list(by_doc)):
            reason = _skip_reason(chunk)
            if reason:
                draft.skipped[reason] = draft.skipped.get(reason, 0) + 1
                continue
            if chunk.chunk_id in seen_origins:
                continue
            seen_origins.add(chunk.chunk_id)
            parts, assets = await self._parts(chunk)
            draft.assets.extend(assets)
            if chunk.question_kwd:
                _mark_question_substitution(draft, kb_id)
            if chunk.mom_id:
                draft.parents[chunk.chunk_id] = chunk.mom_id
            draft.segments.append(_segment(snapshot_id, chunk, by_doc[chunk.doc_id], parts))
        for doc in documents:
            count = sum(1 for segment in draft.segments if segment.origin.doc_id == doc.id)
            draft.documents.append(
                SourceDocument(
                    id=new_id("document"),
                    snapshot_id=snapshot_id,
                    kb_id=kb_id,
                    doc_id=doc.id,
                    name=doc.name,
                    suffix=doc.suffix,
                    content_hash=doc.content_hash,
                    chunk_count=count,
                )
            )

    async def _parts(self, chunk: Chunk) -> tuple[list[ContentPart], list[FrozenAsset]]:
        parts: list[ContentPart] = []
        assets: list[FrozenAsset] = []
        if chunk.content.strip():
            parts.append(ContentPart(type="text" if chunk.doc_type != "table" else "table", text=chunk.content))
        if chunk.img_id:
            data, mime = await self._gateway.get_asset(chunk.img_id)
            digest = hashlib.sha256(data).hexdigest()
            asset_id = f"sha256:{digest}"
            assets.append(FrozenAsset(asset_id=asset_id, data=data, mime=mime, origin_img_id=chunk.img_id))
            parts.append(
                ContentPart(
                    type="image",
                    asset_id=asset_id,
                    mime=mime,
                    region=None if chunk.bbox is None else _region(chunk),
                )
            )
        return parts, assets


def drifted_documents(frozen: list[SourceDocument], current: list[Document]) -> list[str]:
    """Documents whose content hash changed, or that no longer exist.

    A snapshot is immutable, so drift is reported and never repaired in place.
    """
    current_by_id = {document.id: document for document in current}
    drifted = []
    for document in frozen:
        found = current_by_id.get(document.doc_id)
        if found is None or found.content_hash != document.content_hash:
            drifted.append(document.doc_id)
    return drifted


def _is_ready(doc: Document) -> bool:
    return doc.run in _READY and doc.progress >= 1


def _skip_reason(chunk: Chunk) -> str | None:
    if chunk.available == 0:
        return "unavailable"
    if chunk.is_toc:
        return "toc"
    if chunk.is_raptor:
        return "raptor"
    if not chunk.content.strip() and not chunk.img_id:
        return "empty"
    return None


def _region(chunk: Chunk):
    from datafactory.domain.content import Region

    return Region(page=chunk.page, bbox=chunk.bbox)


def _segment(snapshot_id: str, chunk: Chunk, document: Document, parts: list[ContentPart]) -> Segment:
    order = chunk.position[0] if chunk.position and isinstance(chunk.position[0], int) else 0
    return Segment(
        id=new_id("segment"),
        snapshot_id=snapshot_id,
        origin=SegmentOrigin(
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            content_hash=content_hash(parts),
        ),
        modality=modality_of(parts),
        parts=parts,
        title=chunk.title or document.name,
        position=Position(page=chunk.page, order=order, top=chunk.top),
        hash=content_hash(parts),
        minhash=minhash_of(parts),
        tokens=tokens_of(parts),
        meta={"important_kwd": chunk.important_kwd, "question_kwd": chunk.question_kwd, "tags": chunk.tag_kwd},
    )


def _mark_question_substitution(draft: SnapshotDraft, kb_id: str) -> None:
    for profile in draft.vector_profile:
        if profile.get("kb_id") == kb_id:
            profile["vector_semantics"]["question_substitution"] = True


def _link_parents(draft: SnapshotDraft) -> None:
    """Point a child segment at its parent's platform id. The link stays inside the snapshot."""
    by_chunk = {segment.origin.chunk_id: segment for segment in draft.segments}
    for segment in draft.segments:
        parent = by_chunk.get(draft.parents.get(segment.origin.chunk_id, ""))
        if parent is not None and parent.id != segment.id:
            segment.parent_segment_id = parent.id


def _assign_families(draft: SnapshotDraft) -> None:
    """Cluster documents whose segments are near-duplicates of each other.

    The family id is what the leakage-safe split groups on, so two documents
    that share most of their text can never land in different splits.
    """
    signatures = _document_signatures(draft)
    families: list[list[str]] = []
    for doc_id, signature in signatures.items():
        placed = False
        for family in families:
            if any(jaccard(signature, signatures[other]) >= _NEAR_DUP for other in family):
                family.append(doc_id)
                placed = True
                break
        if not placed:
            families.append([doc_id])
    family_of = {doc_id: f"family_{index}" for index, family in enumerate(families) for doc_id in family}
    for document in draft.documents:
        document.family_id = family_of.get(document.doc_id, f"family_{document.doc_id}")


def _document_signatures(draft: SnapshotDraft) -> dict[str, list[int]]:
    """One signature per document, from the union of its segment tokens."""
    grouped: dict[str, list[int]] = {}
    for segment in draft.segments:
        if not segment.minhash:
            continue
        current = grouped.get(segment.origin.doc_id)
        grouped[segment.origin.doc_id] = segment.minhash if current is None else _merge(current, segment.minhash)
    return grouped


def _merge(left: list[int], right: list[int]) -> list[int]:
    """MinHash is a minimum; merging keeps the smaller value per permutation."""
    return [min(a, b) for a, b in zip(left, right, strict=True)]


def health_of(draft: SnapshotDraft) -> HealthReport:
    """Length, garbage, duplication and modality figures for a frozen snapshot."""
    segments = draft.segments
    count = len(segments)
    lengths = [segment.tokens for segment in segments]
    hashes = [segment.hash for segment in segments]
    duplicated = len(hashes) - len(set(hashes))
    near = _near_duplicate_count(segments)
    modalities: dict[str, int] = {}
    garbage = 0
    for segment in segments:
        modalities[segment.modality] = modalities.get(segment.modality, 0) + 1
        text = " ".join(part.text or "" for part in segment.parts)
        if garbage_ratio(text) > 0.05:
            garbage += 1
    short = sum(1 for length in lengths if length < _SHORT)
    long = sum(1 for length in lengths if length > _LONG)

    def ratio(value: int) -> float:
        return round(value / count, 4) if count else 0.0

    return HealthReport(
        segment_count=count,
        document_count=len(draft.documents),
        modality_counts=modalities,
        length={
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "mean": round(sum(lengths) / count, 1) if count else 0,
        },
        short_ratio=ratio(short),
        long_ratio=ratio(long),
        garbage_ratio=ratio(garbage),
        exact_duplicate_ratio=ratio(duplicated),
        near_duplicate_ratio=ratio(near),
        family_count=len({document.family_id for document in draft.documents}),
        skipped=dict(draft.skipped),
        not_ready=list(draft.not_ready),
    )


def _near_duplicate_count(segments: list[Segment]) -> int:
    """Segments whose signature matches an earlier segment above the threshold."""
    seen: list[list[int]] = []
    count = 0
    for segment in segments:
        if not segment.minhash:
            continue
        if any(jaccard(segment.minhash, earlier) >= _NEAR_DUP for earlier in seen):
            count += 1
        else:
            seen.append(segment.minhash)
    return count


def _finish_draft(draft: SnapshotDraft) -> None:
    _assign_families(draft)
    draft.health = health_of(draft)
