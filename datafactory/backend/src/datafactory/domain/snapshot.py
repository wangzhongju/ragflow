"""Data produced by a snapshot build, independent of its builder and persistence."""

from dataclasses import dataclass, field

from datafactory.domain.content import HealthReport, Segment, SourceDocument


@dataclass
class FrozenAsset:
    asset_id: str
    data: bytes
    mime: str
    origin_img_id: str


@dataclass
class SnapshotDraft:
    documents: list[SourceDocument] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    assets: list[FrozenAsset] = field(default_factory=list)
    vector_profile: list[dict] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    not_ready: list[str] = field(default_factory=list)
    parents: dict[str, str] = field(default_factory=dict)
    health: HealthReport | None = None
