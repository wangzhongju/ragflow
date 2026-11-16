"""Freezing a corpus: skip rules, families, assets, health and idempotent rebuilds."""

import hashlib
import json

import httpx
import pytest

from datafactory.core.settings import GatewaySettings
from datafactory.corpus.snapshot import SnapshotBuilder, drifted_documents
from datafactory.domain.content import SourceDocument
from datafactory.gateway.client import GatewayClient
from datafactory.store.projects import ProjectRepository
from datafactory.store.snapshots import SnapshotRepository
from datafactory.store.tables import SegmentRow

_PNG = b"\x89PNG\r\n\x1a\nfake"


def _doc(doc_id: str, name: str = "law.pdf", content_hash: str = "h1", run: str = "DONE") -> dict:
    return {
        "id": doc_id,
        "name": name,
        "suffix": "pdf",
        "type": "pdf",
        "size": 10,
        "content_hash": content_hash,
        "chunk_num": 1,
        "token_num": 10,
        "run": run,
        "progress": 1,
        "status": "1",
        "update_time": 0,
        "parser_id": "naive",
    }


def _chunk(chunk_id: str, doc_id: str, content: str, **extra) -> dict:
    row = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "kb_id": "kb1",
        "content": content,
        "doc_type": "text",
        "title": "law.pdf",
    }
    row.update(extra)
    return row


def _dataset() -> dict:
    return {
        "id": "kb1",
        "name": "Laws",
        "tenant_id": "t1",
        "embd_id": "bge@local",
        "vector_dim": 3,
        "parser_id": "naive",
        "doc_num": 1,
        "chunk_num": 1,
        "vector_similarity_weight": 0.3,
    }


def _client(routes: dict) -> GatewayClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/v1/gateway/assets/"):
            return httpx.Response(200, content=_PNG, headers={"X-Gateway-Version": "1", "content-type": "image/png"})
        body = routes[path]
        if path.endswith("chunks:scan"):
            content = "\n".join(json.dumps(row) for row in body) + "\n"
            return httpx.Response(200, content=content, headers={"X-Gateway-Version": "1"})
        return httpx.Response(200, json={"code": 0, "data": body, "message": ""}, headers={"X-Gateway-Version": "1"})

    settings = GatewaySettings(
        gateway_base_url="http://gateway.test/api/v1", gateway_service_key="k", gateway_version="1"
    )
    return GatewayClient(settings, "u1", transport=httpx.MockTransport(handler))


def _routes(documents: list[dict], chunks: list[dict]) -> dict:
    lines = [*chunks, {"_eof": True, "doc_id": documents[0]["id"], "count": len(chunks)}]
    return {
        "/api/v1/gateway/documents:list": {"total": len(documents), "next_cursor": None, "documents": documents},
        "/api/v1/gateway/datasets": [_dataset()],
        "/api/v1/gateway/chunks:scan": lines,
    }


async def test_ready_documents_freeze_and_the_rest_are_listed():
    documents = [_doc("d1"), _doc("d2", run="RUNNING")]
    chunks = [
        _chunk("c1", "d1", "The statute requires notice before revocation of a licence."),
        _chunk("c2", "d1", "", available=0),
        _chunk("c3", "d1", "contents", is_toc=True),
        _chunk("c4", "d1", "summary", is_raptor=True),
        _chunk("c5", "d1", "   "),
    ]
    draft = await SnapshotBuilder(_client(_routes(documents, chunks))).build("snap_1", [{"kb_id": "kb1"}])

    assert [segment.origin.chunk_id for segment in draft.segments] == ["c1"]
    assert draft.skipped == {"unavailable": 1, "toc": 1, "raptor": 1, "empty": 1}
    assert draft.not_ready == ["d2"]
    assert draft.documents[0].chunk_count == 1
    assert draft.vector_profile[0]["embd_id"] == "bge@local"
    assert draft.vector_profile[0]["vector_semantics"]["title_weight"] == 0.1
    assert draft.vector_profile[0]["vector_semantics"]["question_substitution"] is False


async def test_images_are_stored_once_per_content_hash_and_parents_link():
    documents = [_doc("d1")]
    chunks = [
        _chunk("parent", "d1", "The parent passage states the rule about notice."),
        _chunk("child", "d1", "The child passage quotes the rule about notice.", img_id="bucket-obj", mom_id="parent"),
    ]
    routes = _routes(documents, chunks)
    routes["/api/v1/gateway/chunks:scan"][-1]["count"] = 2
    draft = await SnapshotBuilder(_client(routes)).build("snap_1", [{"kb_id": "kb1"}])

    child = next(segment for segment in draft.segments if segment.origin.chunk_id == "child")
    parent = next(segment for segment in draft.segments if segment.origin.chunk_id == "parent")
    assert child.parent_segment_id == parent.id
    assert child.modality == "mixed"
    assert draft.assets[0].asset_id == "sha256:" + hashlib.sha256(_PNG).hexdigest()
    assert len(draft.assets) == 1


async def test_near_duplicate_documents_share_a_family():
    shared = (
        "The applicant shall give written notice thirty days before revocation of the licence granted under section 4."
    )
    documents = [_doc("d1", "a.pdf"), _doc("d2", "b.pdf")]
    chunks = [_chunk("c1", "d1", shared), _chunk("c2", "d2", shared + " extra words")]
    routes = _routes(documents, chunks)
    routes["/api/v1/gateway/documents:list"]["documents"] = documents
    routes["/api/v1/gateway/chunks:scan"] = [
        chunks[0],
        {"_eof": True, "doc_id": "d1", "count": 1},
        chunks[1],
        {"_eof": True, "doc_id": "d2", "count": 1},
    ]
    draft = await SnapshotBuilder(_client(routes)).build("snap_1", [{"kb_id": "kb1"}])

    families = {document.doc_id: document.family_id for document in draft.documents}
    assert families["d1"] == families["d2"]
    assert draft.health is not None
    assert draft.health.near_duplicate_ratio > 0


async def test_distinct_documents_do_not_share_a_family():
    documents = [_doc("d1"), _doc("d2")]
    chunks = [
        _chunk("c1", "d1", "Quantum tunnelling explains alpha decay in heavy nuclei."),
        _chunk("c2", "d2", "Sourdough fermentation depends on wild yeast and lactic bacteria."),
    ]
    routes = _routes(documents, chunks)
    routes["/api/v1/gateway/chunks:scan"] = [
        chunks[0],
        {"_eof": True, "doc_id": "d1", "count": 1},
        chunks[1],
        {"_eof": True, "doc_id": "d2", "count": 1},
    ]
    draft = await SnapshotBuilder(_client(routes)).build("snap_1", [{"kb_id": "kb1"}])
    families = {document.family_id for document in draft.documents}
    assert len(families) == 2


def test_drift_is_a_changed_hash_or_a_missing_document():
    from datafactory.gateway.dto import Document

    frozen = [
        SourceDocument(
            id="doc_1",
            snapshot_id="s",
            kb_id="kb1",
            doc_id="d1",
            name="a",
            suffix="pdf",
            content_hash="h1",
            chunk_count=1,
        ),
        SourceDocument(
            id="doc_2",
            snapshot_id="s",
            kb_id="kb1",
            doc_id="d2",
            name="b",
            suffix="pdf",
            content_hash="h2",
            chunk_count=1,
        ),
    ]
    current = [Document.model_validate(_doc("d1", content_hash="h1-changed"))]
    assert drifted_documents(frozen, current) == ["d1", "d2"]


@pytest.fixture
async def project(session):
    return await ProjectRepository(session).create("u1", "Laws", "")


async def test_rebuilding_keeps_one_segment_per_origin(session, project):
    documents = [_doc("d1")]
    chunks = [_chunk("c1", "d1", "The statute requires notice.")]
    repo = SnapshotRepository(session)
    record = await repo.create(project.id, "u1", "first", [{"kb_id": "kb1"}])
    draft = await SnapshotBuilder(_client(_routes(documents, chunks))).build(record.id, [{"kb_id": "kb1"}])

    await repo.save_build(record.id, draft)
    await repo.save_build(record.id, draft)

    stored = (await session.execute(SegmentRow.__table__.select())).all()
    assert len(stored) == 1
    saved = await repo.get(record.id)
    assert saved.status == "ready"
    assert (await repo.health(record.id)).segment_count == 1


async def test_a_changed_hash_marks_the_snapshot_stale(session, project):
    documents = [_doc("d1")]
    repo = SnapshotRepository(session)
    record = await repo.create(project.id, "u1", "first", [{"kb_id": "kb1"}])
    draft = await SnapshotBuilder(_client(_routes(documents, [_chunk("c1", "d1", "notice")]))).build(
        record.id, [{"kb_id": "kb1"}]
    )
    await repo.save_build(record.id, draft)

    frozen = await repo.documents(record.id)
    changed = [
        __import__("datafactory.gateway.dto", fromlist=["Document"]).Document.model_validate(
            _doc("d1", content_hash="other")
        )
    ]
    updated = await repo.mark_stale(record.id, drifted_documents(frozen, changed))
    assert updated.status == "stale"
