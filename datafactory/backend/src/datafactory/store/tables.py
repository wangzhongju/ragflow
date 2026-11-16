"""ORM tables. These rows never cross the repository boundary.

Project membership is the platform's own access control. It is checked again
against RAGFlow on every corpus call, so removing a user from a knowledge base
there stops the platform on the next request.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("owner", "editor", "reviewer", "viewer")


class Base(DeclarativeBase):
    """Base for every table."""


class ProjectRow(Base):
    """One data-production project."""

    __tablename__ = "project"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    owner_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MemberRow(Base):
    """A user's role inside one project."""

    __tablename__ = "project_member"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))


class IdempotencyRow(Base):
    """A creation result committed in the same transaction as its resource."""

    __tablename__ = "idempotency"

    scope: Mapped[str] = mapped_column(String(200), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(40))


class SnapshotRow(Base):
    """One frozen corpus. Content is immutable; ``stale`` only marks drift."""

    __tablename__ = "snapshot"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    sources: Mapped[list] = mapped_column(JSON)
    vector_profile: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SourceDocumentRow(Base):
    """A document included in a snapshot, after it was clustered into a family."""

    __tablename__ = "source_document"
    __table_args__ = (UniqueConstraint("snapshot_id", "doc_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(40))
    kb_id: Mapped[str] = mapped_column(String(64))
    doc_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(500))
    suffix: Mapped[str] = mapped_column(String(32), default="")
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer)
    family_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class SegmentRow(Base):
    """A frozen chunk. ``origin_chunk_id`` maps retrieval hits back for this snapshot only."""

    __tablename__ = "segment"
    __table_args__ = (UniqueConstraint("snapshot_id", "origin_chunk_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(40))
    origin_kb_id: Mapped[str] = mapped_column(String(64))
    origin_doc_id: Mapped[str] = mapped_column(String(64))
    origin_chunk_id: Mapped[str] = mapped_column(String(64))
    modality: Mapped[str] = mapped_column(String(16))
    parts: Mapped[list] = mapped_column(JSON)
    title: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[dict] = mapped_column(JSON)
    parent_segment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80))
    minhash: Mapped[list] = mapped_column(JSON, default=list)
    tokens: Mapped[int] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class AssetRow(Base):
    """One stored asset, addressed by its SHA-256. Bytes live in object storage."""

    __tablename__ = "asset"

    asset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    storage_uri: Mapped[str] = mapped_column(Text)


class RecipeRow(Base):
    """A recipe draft. Versions are separate immutable rows."""

    __tablename__ = "recipe"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    task: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=0)


class RecipeVersionRow(Base):
    """An immutable copy of a recipe config."""

    __tablename__ = "recipe_version"
    __table_args__ = (UniqueConstraint("recipe_id", "number", name="uq_recipe_version_number"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    recipe_id: Mapped[str] = mapped_column(String(40))
    number: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)


class RunRow(Base):
    """One execution of a recipe against a snapshot."""

    __tablename__ = "run"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40))
    recipe_id: Mapped[str] = mapped_column(String(40))
    snapshot_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_n: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str] = mapped_column(String(64), default="")
    recipe_version_id: Mapped[str] = mapped_column(String(40), default="")
    mode: Mapped[str] = mapped_column(String(16), default="run")
    seed: Mapped[int] = mapped_column(Integer, default=1)
    batch_size: Mapped[int] = mapped_column(Integer, default=64)
    attempt_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_units: Mapped[int] = mapped_column(Integer, default=0)
    total_units: Mapped[int] = mapped_column(Integer, default=0)
    max_invocations: Mapped[int] = mapped_column(Integer, default=1000)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1000000)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    invocation_count: Mapped[int] = mapped_column(Integer, default=0)
    preview: Mapped[list] = mapped_column(JSON, default=list)


class RunCheckpointRow(Base):
    """A committed column batch; its immutable Parquet object precedes the commit."""

    __tablename__ = "run_checkpoint"
    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    stage: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_generation: Mapped[int] = mapped_column(Integer)
    column_name: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(300))
    row_count: Mapped[int] = mapped_column(Integer)
    elapsed_ms: Mapped[int] = mapped_column(Integer)


class InvocationRow(Base):
    """One dispatched call. Unknown outcomes retain their token reservation."""

    __tablename__ = "invocation"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    call_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("run_id", "call_key", name="uq_invocation_call"),)
    column_name: Mapped[str] = mapped_column(String(200))
    row_key: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(200))
    model_fingerprint: Mapped[str] = mapped_column(String(200), default="")
    attempt_generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    token_upper_bound: Mapped[int] = mapped_column(Integer)
    request_digest: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DatasetRow(Base):
    """The samples one run produced."""

    __tablename__ = "dataset"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    sample_count: Mapped[int] = mapped_column(Integer, default=0)


class SampleRow(Base):
    """One retrieval sample."""

    __tablename__ = "sample"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    positives: Mapped[list] = mapped_column(JSON)
    negatives: Mapped[list] = mapped_column(JSON)
    split: Mapped[str] = mapped_column(String(16))
    modality: Mapped[str] = mapped_column(String(16))
    review_status: Mapped[str] = mapped_column(String(16))
    body: Mapped[dict] = mapped_column(JSON)


class ReviewRow(Base):
    """A human decision over a sample. The sample keeps its original body."""

    __tablename__ = "review"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    sample_id: Mapped[str] = mapped_column(String(40))
    reviewer_id: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")


class ReleaseRow(Base):
    """A frozen set of approved samples with the gate results that allowed it."""

    __tablename__ = "release"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    sample_count: Mapped[int] = mapped_column(Integer)
    gates: Mapped[list] = mapped_column(JSON)
    samples: Mapped[list] = mapped_column(JSON)
