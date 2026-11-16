"""The multimodal content unit and the frozen corpus it belongs to.

Every piece of content the platform stores — a segment, a query, an answer, a
message — is a list of ``ContentPart``. Media is referenced by its content hash,
never embedded. A snapshot freezes the text and the asset bytes; the vectors
stay in RAGFlow.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PartType = Literal["text", "image", "audio", "video", "table", "json"]
Modality = Literal["text", "image", "audio", "video", "table", "mixed"]


class Region(BaseModel):
    """Where inside an asset a part comes from. Cropping does not create an asset."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    bbox: list[float] | None = None
    time_span_ms: list[int] | None = None


class ContentPart(BaseModel):
    """One unit of content. Framework placeholders are never stored here."""

    model_config = ConfigDict(extra="forbid")

    type: PartType
    text: str | None = None
    html: str | None = None
    asset_id: str | None = None
    mime: str | None = None
    region: Region | None = None
    lang: str | None = None
    meta: dict = Field(default_factory=dict)


class SegmentOrigin(BaseModel):
    """Where a frozen segment came from. The chunk id is valid for this snapshot only."""

    model_config = ConfigDict(extra="forbid")

    kb_id: str
    doc_id: str
    chunk_id: str
    content_hash: str


class Position(BaseModel):
    """Where a segment sits inside its document."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    order: int = 0
    top: int | None = None


class Segment(BaseModel):
    """One frozen chunk. ``hash`` covers the normalized parts, not the vector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    snapshot_id: str
    origin: SegmentOrigin
    modality: Modality
    parts: list[ContentPart]
    title: str
    position: Position
    parent_segment_id: str | None = None
    hash: str
    minhash: list[int] = Field(default_factory=list)
    tokens: int
    meta: dict = Field(default_factory=dict)


class SourceDocument(BaseModel):
    """One document included in a snapshot, with the family it was clustered into."""

    model_config = ConfigDict(extra="forbid")

    id: str
    snapshot_id: str
    kb_id: str
    doc_id: str
    name: str
    suffix: str
    content_hash: str | None
    chunk_count: int
    family_id: str | None = None


class HealthReport(BaseModel):
    """The corpus check for one snapshot. Problems are fixed in RAGFlow, then re-snapshotted."""

    model_config = ConfigDict(extra="forbid")

    segment_count: int
    document_count: int
    modality_counts: dict[str, int]
    length: dict[str, float]
    short_ratio: float
    long_ratio: float
    garbage_ratio: float
    exact_duplicate_ratio: float
    near_duplicate_ratio: float
    family_count: int
    skipped: dict[str, int]
    not_ready: list[str]
