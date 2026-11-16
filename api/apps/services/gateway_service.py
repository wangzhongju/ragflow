#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Read-only corpus and model surface consumed by the DataFactory platform.

The service composes existing RAGFlow capabilities (Dealer, LLMBundle, the
knowledge base and document services, object storage) and adds no tables of
its own. It never writes to the document store, the database, or storage.

Stored vectors are retrieval-view vectors: the embedding pipeline mixes the
document title in and, when a chunk carries ``question_kwd``, encodes the
questions instead of the content. Callers may use them for candidate recall,
not for scoring.
"""

import hashlib
import os
import re
import time

from api.db.db_models import Document, TenantModel, UserTenant
from api.db.joint_services.tenant_model_service import resolve_model_config
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.llm_service import LLMBundle
from api.db.services.user_service import TenantService
from common import settings
from common.constants import LLMType, ModelTypeBinary, RetCode
from common.doc_store.doc_store_base import MatchDenseExpr, OrderByExpr
from common.llm_request_context import normalize_llm_user_id, reset_llm_request_context, set_llm_request_context
from common.misc_utils import thread_pool_exec
from rag.nlp import search
from rag.utils.base64_image import parse_storage_composite_id

GATEWAY_VERSION = "1"

# The embedding pipeline weights the document title into every stored vector
# with this default (rag/svr/task_executor.py). Reported so callers know the
# vectors are not pure content vectors.
TITLE_EMBED_WEIGHT = 0.1

# chunk_list pages internally at 128 rows, so 1024 is a single round trip and
# keeps the per-document memory bounded for very large documents.
SCAN_BATCH_SIZE = 1024

VECTOR_FETCH_LIMIT = 1024

SERVICE_KEY_HEADER = "X-DF-Service-Key"
USER_HEADER = "X-DF-User-Id"
REQUEST_HEADER = "X-DF-Request-Id"

OP_CHAT = "chat"
OP_EMBED_DOCUMENTS = "embed_documents"
OP_EMBED_QUERY = "embed_query"
OP_RERANK = "rerank"
OP_DESCRIBE = "describe"
OP_TRANSCRIBE = "transcribe"

_OP_MODEL_TYPE = {
    OP_CHAT: LLMType.CHAT.value,
    OP_EMBED_DOCUMENTS: LLMType.EMBEDDING.value,
    OP_EMBED_QUERY: LLMType.EMBEDDING.value,
    OP_RERANK: LLMType.RERANK.value,
    OP_DESCRIBE: LLMType.VISION.value,
    OP_TRANSCRIBE: LLMType.ASR.value,
}

# Fields a scan may request. Vector fields are never part of a scan; vectors
# are fetched separately so the stream stays small.
SCAN_FIELDS = {
    "content_with_weight",
    "doc_type_kwd",
    "img_id",
    "docnm_kwd",
    "page_num_int",
    "position_int",
    "top_int",
    "mom_id",
    "available_int",
    "question_kwd",
    "important_kwd",
    "tag_kwd",
    "toc_kwd",
    "raptor_kwd",
    "doc_id",
    "kb_id",
}

_DEFAULT_SCAN_FIELDS = [
    "content_with_weight",
    "doc_type_kwd",
    "img_id",
    "docnm_kwd",
    "page_num_int",
    "position_int",
    "top_int",
    "mom_id",
    "available_int",
    "question_kwd",
    "important_kwd",
    "tag_kwd",
    "toc_kwd",
    "raptor_kwd",
]


class GatewayError(Exception):
    """Error carrying the RetCode the route layer maps onto the response."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def gateway_enabled() -> bool:
    return bool(os.environ.get("DATAFACTORY_SERVICE_KEY", "").strip())


def max_inflight() -> int:
    raw = os.environ.get("DATAFACTORY_GATEWAY_MAX_INFLIGHT", "32").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 32
    return max(1, value)


def _require_kb(kb_id: str, user_id: str):
    if not KnowledgebaseService.accessible(kb_id, user_id):
        raise GatewayError(RetCode.PERMISSION_ERROR, f"Knowledge base {kb_id} is not accessible.")
    ok, kb = KnowledgebaseService.get_by_id(kb_id)
    if not ok:
        raise GatewayError(RetCode.NOT_FOUND, f"Knowledge base {kb_id} not found.")
    return kb


def joined_tenant_ids(user_id: str) -> list[str]:
    """Tenants the user belongs to, always including the user's own tenant."""
    rows = UserTenant.select(UserTenant.tenant_id).where(UserTenant.user_id == user_id)
    return sorted({user_id, *(row.tenant_id for row in rows)})


def _model_fingerprint(model_config: dict) -> str:
    raw = f"{model_config.get('llm_factory', '')}|{model_config.get('llm_name', '')}|{model_config.get('model_type', '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _usage(prompt: int = 0, completion: int = 0, total: int | None = None) -> dict:
    total = int(total if total is not None else prompt + completion)
    return {"prompt_tokens": int(prompt), "completion_tokens": int(completion), "total_tokens": total}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value else []
    return [value]


def _first_int(value) -> int | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _bbox(position_int) -> list[float] | None:
    """RAGFlow stores one position as [page, left, right, top, bottom]."""
    values = position_int[0] if position_int and isinstance(position_int[0], list) else position_int
    if not isinstance(values, list) or len(values) < 5:
        return None
    try:
        left, right, top, bottom = (float(v) for v in values[1:5])
    except (TypeError, ValueError):
        return None
    return [left, top, right, bottom]


def normalize_chunk(chunk: dict) -> dict:
    """Turn one doc-store chunk into the stable record the platform consumes."""
    position = chunk.get("position_int")
    page = _first_int(chunk.get("page_num_int"))
    if page is None and isinstance(position, list) and position:
        head = position[0][0] if isinstance(position[0], list) and position[0] else position[0]
        page = _first_int(head)
    return {
        "chunk_id": chunk.get("id", ""),
        "doc_id": chunk.get("doc_id", ""),
        "kb_id": chunk.get("kb_id", ""),
        "content": chunk.get("content_with_weight", "") or "",
        "doc_type": chunk.get("doc_type_kwd", "") or "text",
        "img_id": chunk.get("img_id", "") or "",
        "title": chunk.get("docnm_kwd", "") or "",
        "page": page,
        "position": position if isinstance(position, list) else [],
        "bbox": _bbox(position),
        "top": _first_int(chunk.get("top_int")),
        "mom_id": chunk.get("mom_id", "") or "",
        "available": _first_int(chunk.get("available_int")),
        "question_kwd": _as_list(chunk.get("question_kwd")),
        "important_kwd": _as_list(chunk.get("important_kwd")),
        "tag_kwd": _as_list(chunk.get("tag_kwd")),
        "is_toc": bool(chunk.get("toc_kwd")),
        "is_raptor": bool(chunk.get("raptor_kwd")),
    }


def list_datasets(user_id: str) -> list[dict]:
    """Knowledge bases the user can read, each with its stored vector dimension.

    The dimension comes from one stored chunk's ``q_{dim}_vec`` field. A base
    with no chunks yet reports ``vector_dim`` as null.
    """
    tenant_ids = joined_tenant_ids(user_id)
    kbs, _total = KnowledgebaseService.get_by_tenant_ids(tenant_ids, user_id, 0, 0, "create_time", True, "", None)
    return [
        {
            "id": kb["id"],
            "name": kb["name"],
            "tenant_id": kb["tenant_id"],
            "embd_id": kb["embd_id"],
            "tenant_embd_id": kb.get("tenant_embd_id"),
            "vector_dim": vector_dim_of(kb["id"]),
            "parser_id": kb["parser_id"],
            "pipeline_id": kb.get("pipeline_id"),
            "doc_num": kb["doc_num"],
            "chunk_num": kb["chunk_num"],
            "similarity_threshold": kb.get("similarity_threshold"),
            "vector_similarity_weight": kb.get("vector_similarity_weight"),
            "filename_embd_weight": (kb.get("parser_config") or {}).get("filename_embd_weight"),
        }
        for kb in kbs
    ]


def vector_dim_of(kb_id: str) -> int | None:
    """Dimension of the vectors stored for one knowledge base, or None when it has none."""
    ok, kb = KnowledgebaseService.get_by_id(kb_id)
    if not ok or not kb.chunk_num:
        return None
    docs, _ = DocumentService.get_by_kb_id(kb.id, 1, 1, "create_time", True, "", run_status=[], types=[], suffix=[])
    if not docs:
        return None
    dealer = search.Dealer(settings.docStoreConn)
    chunks = dealer.chunk_list(docs[0]["id"], kb.tenant_id, [kb.id], max_count=1, fields=["doc_id"])
    if not chunks:
        return None
    raw = settings.docStoreConn.get(chunks[0]["id"], search.index_name(kb.tenant_id), [kb.id])
    if not raw:
        return None
    for key, value in raw.items():
        if key.startswith("q_") and key.endswith("_vec") and isinstance(value, list):
            return len(value)
    return None


def list_documents(user_id: str, kb_id: str, doc_ids: list[str] | None, page_cursor: str | None, page_size: int) -> dict:
    """One page of documents, ordered by id, with a cursor for the next page.

    The cursor is the last id returned. Passing it back yields the following
    page, so a client can walk a knowledge base without relying on offsets.
    """
    _require_kb(kb_id, user_id)
    docs, total = DocumentService.get_by_kb_id(kb_id, 0, 0, "id", False, "", run_status=[], types=[], suffix=[], doc_ids=doc_ids or None)
    if page_cursor:
        docs = [doc for doc in docs if doc["id"] > page_cursor]
    page = docs[:page_size]
    next_cursor = page[-1]["id"] if len(docs) > page_size else None
    return {"total": total, "next_cursor": next_cursor, "documents": [_document_record(doc) for doc in page]}


def _document_record(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "name": doc["name"],
        "suffix": doc.get("suffix", ""),
        "type": doc["type"],
        "size": doc["size"],
        "content_hash": doc.get("content_hash", ""),
        "chunk_num": doc["chunk_num"],
        "token_num": doc["token_num"],
        "run": doc["run"],
        "progress": doc["progress"],
        "status": doc["status"],
        "update_time": doc.get("update_time"),
        "parser_id": doc["parser_id"],
        "pipeline_id": doc.get("pipeline_id"),
    }


def document_ready(user_id: str, kb_id: str, doc_id: str) -> Document:
    """Return the document when the user may read it, else raise."""
    _require_kb(kb_id, user_id)
    ok, doc = DocumentService.get_by_id(doc_id)
    if not ok or doc.kb_id != kb_id:
        raise GatewayError(RetCode.NOT_FOUND, f"Document {doc_id} not found in knowledge base {kb_id}.")
    return doc


def scan_batch(tenant_id: str, kb_id: str, doc_id: str, offset: int, fields: list[str] | None) -> list[dict]:
    """One page of a document's chunks, normalized.

    Callers loop with the returned length until a short page arrives, which
    keeps memory bounded for documents far larger than ``SCAN_BATCH_SIZE``.
    Vectors are not included here; ``attach_vectors`` adds them when the caller
    asked for ``include_vector``.
    """
    selected = [field for field in (fields or _DEFAULT_SCAN_FIELDS) if field in SCAN_FIELDS]
    if "doc_id" not in selected:
        selected.append("doc_id")
    chunks = search.Dealer(settings.docStoreConn).chunk_list(
        doc_id,
        tenant_id,
        [kb_id],
        max_count=offset + SCAN_BATCH_SIZE,
        offset=offset,
        fields=selected,
        sort_by_position=True,
    )
    return [normalize_chunk(chunk) for chunk in chunks]


async def attach_vectors(tenant_id: str, kb_id: str, records: list[dict]) -> list[dict]:
    """Add the stored retrieval-view vector to each record.

    Chunks without a stored vector keep ``vector`` as null. The dimension is
    reported on every record so a consumer can tell an empty vector from a
    knowledge base that has not been embedded yet.
    """
    dim = vector_dim_of(kb_id)
    if dim is None:
        return [{**record, "vector": None, "vector_dim": None} for record in records]
    dealer = search.Dealer(settings.docStoreConn)
    chunk_ids = [record["chunk_id"] for record in records]
    vectors = await dealer.fetch_chunk_vectors(chunk_ids, tenant_id, [kb_id], dim)
    return [{**record, "vector": _vector(vectors[record["chunk_id"]]) if vectors.get(record["chunk_id"]) else None, "vector_dim": dim} for record in records]


async def fetch_vectors(user_id: str, kb_id: str, chunk_ids: list[str]) -> dict:
    kb = _require_kb(kb_id, user_id)
    if len(chunk_ids) > VECTOR_FETCH_LIMIT:
        raise GatewayError(RetCode.ARGUMENT_ERROR, f"At most {VECTOR_FETCH_LIMIT} chunk ids per request.")
    dim = await _vector_dim(kb)
    if dim is None:
        raise GatewayError(RetCode.DATA_ERROR, f"Knowledge base {kb_id} has no embedding dimension.")
    dealer = search.Dealer(settings.docStoreConn)
    vectors = await dealer.fetch_chunk_vectors(chunk_ids, kb.tenant_id, [kb_id], dim)
    return {"dim": dim, "vectors": {chunk_id: _vector(vector) for chunk_id, vector in vectors.items()}}


async def search_dense(user_id: str, kb_ids: list[str], query: dict, top_k: int, filters: dict | None, min_score: float) -> dict:
    """Vector-only recall over one or more knowledge bases.

    Every knowledge base must share one embedding model and one dimension;
    mixed vector spaces are rejected rather than merged silently.
    """
    if not kb_ids:
        raise GatewayError(RetCode.ARGUMENT_ERROR, "kb_ids is required.")
    kbs = [_require_kb(kb_id, user_id) for kb_id in kb_ids]
    profiles = [(_kb_embed_id(kb), kb.tenant_id) for kb in kbs]
    if len({profile[0] for profile in profiles}) > 1:
        raise GatewayError(RetCode.ARGUMENT_ERROR, "Dense search across knowledge bases requires the same embedding model.")
    dimensions = [await _vector_dim(kb) for kb in kbs]
    if len(set(dimensions)) != 1:
        raise GatewayError(RetCode.ARGUMENT_ERROR, "Dense search requires the same vector dimension in every knowledge base.")
    dim = dimensions[0]
    if dim is None:
        raise GatewayError(RetCode.DATA_ERROR, "Knowledge base has no embedding dimension.")

    vector = await _resolve_query_vector(user_id, kbs[0], query, dim)
    filters = filters or {}
    condition: dict = {}
    if filters.get("doc_ids"):
        condition["doc_id"] = list(filters["doc_ids"])
    if filters.get("doc_types"):
        condition["doc_type_kwd"] = list(filters["doc_types"])
    if filters.get("exclude_chunk_ids"):
        condition["must_not"] = {"id": list(filters["exclude_chunk_ids"])}

    match = MatchDenseExpr(f"q_{dim}_vec", vector, "float", "cosine", top_k, {"similarity": min_score})
    tenant_ids = list({kb.tenant_id for kb in kbs})
    idx_names = [search.index_name(tenant_id) for tenant_id in tenant_ids]
    dealer = search.Dealer(settings.docStoreConn)
    res = await thread_pool_exec(
        dealer.dataStore.search,
        ["doc_id", "kb_id"],
        [],
        condition,
        [match],
        OrderByExpr(),
        0,
        top_k,
        idx_names,
        list(kb_ids),
    )
    fields = dealer.dataStore.get_fields(res, ["doc_id", "kb_id"])
    hits = []
    for chunk_id, score in _knn_hits(dealer, res):
        if score < min_score:
            continue
        doc = fields.get(chunk_id, {})
        hits.append({"chunk_id": chunk_id, "doc_id": doc.get("doc_id", ""), "kb_id": doc.get("kb_id", ""), "score": score})
    return {"dim": dim, "hits": hits[:top_k]}


async def search_production(user_id: str, kb_ids: list[str], question: str, top_k: int, doc_ids: list[str] | None, use_rerank: bool, must_not: dict | None) -> dict:
    """The same hybrid retrieval an online chat uses, with the knowledge base's own weights."""
    if not kb_ids:
        raise GatewayError(RetCode.ARGUMENT_ERROR, "kb_ids is required.")
    if not question or not question.strip():
        raise GatewayError(RetCode.ARGUMENT_ERROR, "question is required.")
    kbs = [_require_kb(kb_id, user_id) for kb_id in kb_ids]
    kb = kbs[0]
    embd_config = resolve_model_config(kb.tenant_id, LLMType.EMBEDDING.value, _kb_embed_id(kb))
    embd_mdl = LLMBundle(kb.tenant_id, embd_config)
    rerank_mdl = None
    if use_rerank:
        rerank_mdl = _optional_rerank_bundle(kb.tenant_id)

    tenant_ids = list({item.tenant_id for item in kbs})
    dealer = settings.retriever
    ranks = await dealer.retrieval(
        question.strip(),
        embd_mdl,
        tenant_ids,
        list(kb_ids),
        1,
        top_k,
        similarity_threshold=kb.similarity_threshold,
        vector_similarity_weight=kb.vector_similarity_weight,
        doc_ids=list(doc_ids) if doc_ids else None,
        aggs=False,
        rerank_mdl=rerank_mdl,
        highlight=False,
        must_not=must_not or None,
    )
    hits = [
        {
            "chunk_id": chunk.get("chunk_id", ""),
            "doc_id": chunk.get("doc_id", ""),
            "kb_id": chunk.get("kb_id", ""),
            "content": chunk.get("content_with_weight", ""),
            "doc_type": chunk.get("doc_type_kwd", ""),
            "img_id": chunk.get("image_id") or chunk.get("img_id", ""),
            "similarity": chunk.get("similarity", 0.0),
            "vector_similarity": chunk.get("vector_similarity", 0.0),
            "term_similarity": chunk.get("term_similarity", 0.0),
        }
        for chunk in ranks.get("chunks", [])
    ]
    return {"total": ranks.get("total", len(hits)), "hits": hits}


def get_asset(user_id: str, img_id: str) -> tuple[bytes, str]:
    """Return the raw bytes behind a chunk ``img_id`` after checking access.

    ``img_id`` is ``{bucket}-{object_key}``. For chunk images the bucket is the
    knowledge base id, so access is checked against it.
    """
    parsed = parse_storage_composite_id(img_id)
    if not parsed:
        raise GatewayError(RetCode.ARGUMENT_ERROR, "Invalid image id.")
    bucket, object_key = parsed
    ok, kb = KnowledgebaseService.get_by_id(bucket)
    if not ok or not KnowledgebaseService.accessible(kb.id, user_id):
        raise GatewayError(RetCode.PERMISSION_ERROR, "Image is not accessible.")
    data = settings.STORAGE_IMPL.get(bucket, object_key)
    if not data:
        raise GatewayError(RetCode.NOT_FOUND, "Image not found.")
    return data, _image_content_type(object_key, data)


def list_models(user_id: str, types: list[str] | None) -> list[dict]:
    tenant_ids = joined_tenant_ids(user_id)
    query = TenantModel.select().where(TenantModel.tenant_id.in_(tenant_ids), TenantModel.status == "active")
    models = []
    for model in query:
        model_types = _model_types(model.model_type)
        if types and not set(model_types) & set(types):
            continue
        models.append(
            {
                "model_id": model.id,
                "tenant_id": model.tenant_id,
                "type": model_types,
                "factory": model.llm_factory,
                "name": model.llm_name,
                "max_tokens": model.max_tokens,
                "capabilities": {
                    "vision": LLMType.VISION.value in model_types,
                    "image_embedding": False,
                    "audio": LLMType.ASR.value in model_types,
                },
            }
        )
    return models


async def invoke_model(user_id: str, model_id: str, op: str, inputs: dict, gen_conf: dict | None) -> dict:
    """Run one model operation and report token usage.

    Prompt assembly stays in the caller. This only dispatches the already
    built inputs to the model the user is allowed to use.
    """
    model_type = _OP_MODEL_TYPE.get(op)
    if model_type is None:
        raise GatewayError(RetCode.ARGUMENT_ERROR, f"Unsupported op {op}.")
    tenant_id = _model_tenant(user_id, model_id, model_type)
    model_config = resolve_model_config(tenant_id, model_type, model_id)
    bundle = LLMBundle(tenant_id, model_config)
    gen_conf = dict(gen_conf or {})
    inputs = inputs or {}

    started = time.perf_counter()
    token = set_llm_request_context(user_id=normalize_llm_user_id(user_id))
    try:
        outputs, usage = await _dispatch_op(bundle, op, inputs, gen_conf)
    finally:
        reset_llm_request_context(token)
    return {
        "outputs": outputs,
        "usage": usage,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model_fingerprint": _model_fingerprint(model_config),
    }


async def _dispatch_op(bundle: LLMBundle, op: str, inputs: dict, gen_conf: dict) -> tuple[dict, dict]:
    if op == OP_CHAT:
        system = inputs.get("system", "")
        history = list(inputs.get("history", []))
        if inputs.get("images") or inputs.get("video_bytes"):
            history.append({"role": "user", "content": inputs.get("content", ""), "image": inputs.get("images", [])})
        # async_chat returns the text only; token accounting stays inside LLMBundle.
        answer = await bundle.async_chat(system, history, gen_conf)
        return {"text": _strip_think(answer)}, _usage()

    if op == OP_EMBED_DOCUMENTS:
        texts = inputs.get("texts", [])
        if not isinstance(texts, list) or not texts:
            raise GatewayError(RetCode.ARGUMENT_ERROR, "texts must be a non-empty list.")
        embeddings, used = await thread_pool_exec(bundle.encode, texts)
        return {"vectors": _vectors(embeddings)}, _usage(total=used)

    if op == OP_EMBED_QUERY:
        text = inputs.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise GatewayError(RetCode.ARGUMENT_ERROR, "text is required.")
        vector, used = await thread_pool_exec(bundle.encode_queries, text)
        return {"vector": _vector(vector)}, _usage(total=used)

    if op == OP_RERANK:
        query = inputs.get("query", "")
        texts = inputs.get("texts", [])
        if not query or not isinstance(texts, list) or not texts:
            raise GatewayError(RetCode.ARGUMENT_ERROR, "query and texts are required.")
        scores, used = await thread_pool_exec(bundle.similarity, query, texts)
        return {"scores": [float(score) for score in scores]}, _usage(total=used)

    if op == OP_DESCRIBE:
        image = inputs.get("image", "")
        if not image:
            raise GatewayError(RetCode.ARGUMENT_ERROR, "image is required.")
        prompt = inputs.get("prompt", "")
        # describe and transcription return only the text; token usage is
        # recorded inside LLMBundle and is not available to the caller.
        if prompt:
            text = await thread_pool_exec(bundle.describe_with_prompt, image, prompt)
        else:
            text = await thread_pool_exec(bundle.describe, image)
        return {"text": text}, _usage()

    if op == OP_TRANSCRIBE:
        audio = inputs.get("audio", "")
        if not audio:
            raise GatewayError(RetCode.ARGUMENT_ERROR, "audio is required.")
        text = await thread_pool_exec(bundle.transcription, audio)
        return {"text": text}, _usage()

    raise GatewayError(RetCode.ARGUMENT_ERROR, f"Unsupported op {op}.")


def _model_tenant(user_id: str, model_id: str, model_type: str) -> str:
    """Return the tenant that owns ``model_id`` when ``user_id`` may use it for ``model_type``."""
    model_obj = TenantModel.get_or_none(TenantModel.id == model_id)
    if model_obj is None:
        raise GatewayError(RetCode.NOT_FOUND, f"Model {model_id} not found.")
    if model_obj.tenant_id not in joined_tenant_ids(user_id):
        raise GatewayError(RetCode.PERMISSION_ERROR, f"Model {model_id} is not available.")
    if not (model_obj.model_type & _type_bit(model_type)):
        raise GatewayError(RetCode.ARGUMENT_ERROR, f"Model {model_id} does not support {model_type}.")
    return model_obj.tenant_id


def _type_bit(model_type: str) -> int:
    return ModelTypeBinary[LLMType(model_type).name].value


def _model_types(bitfield: int) -> list[str]:
    names = []
    for member in ModelTypeBinary:
        if bitfield & member.value:
            names.append(LLMType[member.name].value)
    return names


def _kb_embed_id(kb) -> str:
    return kb.tenant_embd_id or kb.embd_id


async def _vector_dim(kb) -> int | None:
    return vector_dim_of(kb.id)


async def _resolve_query_vector(user_id: str, kb, query: dict, dim: int) -> list[float]:
    if query.get("vector"):
        vector = [float(v) for v in query["vector"]]
        if len(vector) != dim:
            raise GatewayError(RetCode.ARGUMENT_ERROR, f"Query vector has dimension {len(vector)}, expected {dim}.")
        return vector
    if query.get("chunk_id"):
        vectors = await search.Dealer(settings.docStoreConn).fetch_chunk_vectors([query["chunk_id"]], kb.tenant_id, [kb.id], dim)
        vector = vectors.get(query["chunk_id"])
        if not vector or not any(vector):
            raise GatewayError(RetCode.NOT_FOUND, f"No vector for chunk {query['chunk_id']}.")
        return vector
    if query.get("text"):
        result = await invoke_model(user_id, _kb_embed_id(kb), OP_EMBED_QUERY, {"text": query["text"]}, None)
        return result["outputs"]["vector"]
    raise GatewayError(RetCode.ARGUMENT_ERROR, "query needs vector, text, or chunk_id.")


def _optional_rerank_bundle(tenant_id: str) -> LLMBundle | None:
    ok, tenant = TenantService.get_by_id(tenant_id)
    if not ok or not getattr(tenant, "tenant_rerank_id", None):
        return None
    config = resolve_model_config(tenant_id, LLMType.RERANK.value, tenant.tenant_rerank_id)
    return LLMBundle(tenant_id, config)


def _knn_hits(dealer, res) -> list[tuple[str, float]]:
    """Read (chunk id, cosine score) pairs out of a doc-store search result.

    Elasticsearch returns a hit dict, and scores live on ``hits.hits[*]._score``.
    Infinity returns a DataFrame whose ``_score`` column is ``similarity()`` plus
    the pagerank feature. Both shapes are sorted by score descending.
    """
    scores: list[tuple[str, float]] = []
    if hasattr(dealer.dataStore, "get_scores") and isinstance(res, dict):
        scores = [(chunk_id, float(score)) for chunk_id, score in dealer.dataStore.get_scores(res).items()]
    if not scores:
        frame = res[0] if isinstance(res, tuple) else res
        if hasattr(frame, "columns") and "id" in frame.columns and "_score" in frame.columns:
            scores = [(str(row.id), float(row._score or 0.0)) for row in frame.itertuples(index=False)]
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores


def _vectors(embeddings) -> list[list[float]]:
    return [_vector(row) for row in embeddings]


def _vector(value) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(v) for v in value]


def _strip_think(answer: str) -> str:
    return re.sub(r"<think>.*?</think>", "", answer or "", flags=re.DOTALL).strip()


def _image_content_type(object_name: str, data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    name = object_name.lower()
    for suffix, content_type in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".gif", "image/gif"), (".webp", "image/webp")):
        if name.endswith(suffix):
            return content_type
    return "application/octet-stream"
