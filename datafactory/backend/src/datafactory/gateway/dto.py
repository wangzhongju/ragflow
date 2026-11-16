"""Typed records returned by the Corpus Gateway.

Field names match the gateway contract (design §5.2). A gateway response that
is missing a required field fails here, rather than later in a caller.
"""

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Session(_Record):
    """The user a browser login resolved to."""

    user_id: str
    tenant_ids: list[str]
    nickname: str
    lang: str


class Dataset(_Record):
    """One knowledge base the user can read."""

    id: str
    name: str
    tenant_id: str
    embd_id: str
    tenant_embd_id: str | None = None
    vector_dim: int | None
    parser_id: str
    pipeline_id: str | None = None
    doc_num: int
    chunk_num: int
    similarity_threshold: float | None = None
    vector_similarity_weight: float | None = None
    filename_embd_weight: float | None = None


class Document(_Record):
    """One document inside a knowledge base."""

    id: str
    name: str
    suffix: str
    type: str
    size: int
    content_hash: str | None = None
    chunk_num: int
    token_num: int
    run: str
    progress: float
    status: str
    update_time: int
    parser_id: str
    pipeline_id: str | None = None


class DocumentPage(_Record):
    """One cursor page of documents."""

    total: int
    next_cursor: str | None
    documents: list[Document]


class ModelCapabilities(_Record):
    """What a model can accept beyond plain text."""

    vision: bool = False
    image_embedding: bool = False
    audio: bool = False


class Model(_Record):
    """One model the user may call. No credentials travel with it."""

    model_id: str
    tenant_id: str
    type: list[str]
    factory: str
    name: str
    max_tokens: int
    capabilities: ModelCapabilities


class Usage(_Record):
    """Token accounting reported by one model call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Invocation(_Record):
    """The result of one ``models:invoke`` call."""

    outputs: dict
    usage: Usage
    latency_ms: int
    model_fingerprint: str


class Chunk(_Record):
    """One normalized chunk from a ``chunks:scan`` stream."""

    chunk_id: str
    doc_id: str
    kb_id: str
    content: str
    doc_type: str
    img_id: str = ""
    title: str = ""
    page: int | None = None
    position: list = []
    bbox: list[float] | None = None
    top: int | None = None
    mom_id: str = ""
    available: int | None = None
    question_kwd: list[str] = []
    important_kwd: list[str] = []
    tag_kwd: list[str] = []
    is_toc: bool = False
    is_raptor: bool = False
    vector: list[float] | None = None
    vector_dim: int | None = None


class DenseHit(_Record):
    """One hit from a dense search."""

    chunk_id: str
    doc_id: str
    score: float


class DenseSearch(_Record):
    """Dense search results, with the dimension they were scored in."""

    dim: int
    hits: list[DenseHit]
