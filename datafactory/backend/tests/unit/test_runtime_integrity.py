"""Regression tests at the HTTP/service boundaries, using only local SQLite and stubs."""

from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import select
from starlette.requests import Request

from datafactory.app.auth import SESSION_TTL, read_cookie, session_cookie
from datafactory.core.errors import BadRequest, Conflict
from datafactory.core.settings import GatewaySettings
from datafactory.engine.recipe import Recipe
from datafactory.gateway.client import GatewayClient
from datafactory.pipeline.run import produce, release_check
from datafactory.store.projects import Member, ProjectRepository
from datafactory.store.snapshots import SnapshotRepository
from datafactory.store.tables import DatasetRow, ReleaseRow, RunRow, SampleRow, SegmentRow, SnapshotRow


def _recipe(columns=None, **extra):
    return Recipe.model_validate(
        {
            "seed": {"type": "ragflow_snapshot", "snapshot_id": "snap"},
            "columns": columns
            or [{"name": "query", "type": "expression", "params": {"expr": "{{ seed.parts | render_parts }}"}}],
            **extra,
        }
    )


def _segment(id="seg", **extra):
    return {
        "id": id,
        "origin": {"doc_id": "doc", "kb_id": "kb", "chunk_id": id},
        "parts": [{"type": "text", "text": f"Evidence {id}"}],
        "modality": "text",
        **extra,
    }


async def test_production_does_not_fabricate_negative_or_judge_scores():
    samples = await produce(_recipe(), [_segment(), _segment("other")], Mock(spec=GatewayClient), 1, 2)
    assert samples[0]["query"] == "Evidence seg"
    assert samples[0]["negatives"] == []
    assert samples[0]["judge"] == {}
    gates = {item["name"]: item for item in release_check(samples, "ready")}
    assert not gates["example_counts"]["passed"]
    assert not gates["judge_score"]["passed"]


async def test_production_sorts_the_dag_and_drops_failed_rows_before_downstream():
    recipe = _recipe(
        [
            {"name": "query", "type": "expression", "params": {"expr": "{{ value }}"}},
            {"name": "value", "type": "expression", "params": {"expr": "{{ seed.parts | render_parts }}"}},
        ]
    )
    assert (await produce(recipe, [_segment()], Mock(spec=GatewayClient), 1, 1))[0]["query"] == "Evidence seg"
    recipe.columns[1].params["expr"] = "{{ seed.missing }}"
    assert await produce(recipe, [_segment()], Mock(spec=GatewayClient), 1, 1) == []


@pytest.mark.parametrize("path", ["", "/segments", "/health", ":check-staleness"])
async def test_snapshot_endpoints_cannot_cross_projects(client, session, path):
    projects = ProjectRepository(session)
    mine = await projects.create("u1", "mine", "")
    other = await projects.create("u2", "other", "")
    snapshot = await SnapshotRepository(session).create(other.id, "u2", "private", [])
    url = f"/api/factory/v1/projects/{mine.id}/snapshots/{snapshot.id}{path}"
    result = await (client.post(url) if path.startswith(":") else client.get(url))
    assert result.status_code == 404
    assert result.json()["code"] == "snapshot_not_found"


@pytest.mark.parametrize("preview", [False, True])
async def test_run_and_preview_cannot_cross_projects(client, session, preview):
    projects = ProjectRepository(session)
    mine = await projects.create("u1", "mine", "")
    other = await projects.create("u2", "other", "")
    snapshot = await SnapshotRepository(session).create(other.id, "u2", "private", [])
    prefix = f"/api/factory/v1/projects/{mine.id}"
    created = await client.post(f"{prefix}/recipes", json={"name": "recipe", "config": _recipe().model_dump()})
    assert created.status_code == 201
    recipe = created.json()["id"]
    url = f"{prefix}/recipes/{recipe}:preview" if preview else f"{prefix}/runs"
    response = await client.post(url, json={"recipe_id": recipe, "snapshot_id": snapshot.id, "limit": 1})
    assert response.status_code == 404
    assert not (await session.scalars(select(RunRow))).all()


async def test_projects_replay_across_repository_sessions_and_reject_conflicts(app):
    async with app.state.sessions() as session:
        first = await ProjectRepository(session).create("u1", "name", "", "request-key")
    async with app.state.sessions() as session:
        repository = ProjectRepository(session)
        assert (await repository.create("u1", "name", "", "request-key")).id == first.id
        with pytest.raises(Conflict):
            await repository.create("u1", "different", "", "request-key")


async def test_project_with_snapshot_cannot_leave_orphans_and_duplicate_members_are_rejected(session):
    repository = ProjectRepository(session)
    project = await repository.create("u1", "name", "")
    await SnapshotRepository(session).create(project.id, "u1", "snapshot", [])
    with pytest.raises(Conflict, match="containing"):
        await repository.delete(project.id, "u1")
    with pytest.raises(BadRequest, match="only once"):
        await repository.set_members(project.id, "u1", [Member("u1", "owner"), Member("u1", "viewer")])
    assert (await repository.get(project.id, "u1")).role == "owner"


def test_cookie_rejects_tampering_and_expiry(monkeypatch):
    monkeypatch.setattr("datafactory.app.auth.time.time", lambda: 1000)
    name, value = session_cookie("u1", "secret")

    def request(cookie):
        return Request({"type": "http", "headers": [(b"cookie", f"{name}={cookie}".encode())]})

    assert read_cookie(request(value), "secret") == "u1"
    assert read_cookie(request(value.replace("u1", "u2")), "secret") == ""
    monkeypatch.setattr("datafactory.app.auth.time.time", lambda: 1000 + SESSION_TTL)
    assert read_cookie(request(value), "secret") == ""


async def test_review_and_release_details_are_reachable(client, session):
    project = await ProjectRepository(session).create("u1", "name", "")
    session.add(DatasetRow(id="ds", project_id=project.id, run_id="run", name="dataset", sample_count=1))
    session.add(
        SampleRow(
            id="smp",
            dataset_id="ds",
            query="Q",
            positives=["p"],
            negatives=["n"],
            split="train",
            modality="text",
            review_status="pending",
            body={},
        )
    )
    session.add(ReleaseRow(id="rel", dataset_id="ds", status="released", sample_count=1, gates=[], samples=[]))
    await session.commit()
    prefix = f"/api/factory/v1/projects/{project.id}"
    review = await client.post(f"{prefix}/samples/smp/reviews", json={"decision": "approved"})
    assert review.status_code == 200
    assert review.json()["review_status"] == "approved"
    assert (await client.get(f"{prefix}/releases/rel")).json()["id"] == "rel"
    invalid = await client.post(f"{prefix}/samples/smp/reviews", json={"decision": "invalid"})
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "bad_decision"


async def test_missing_run_has_stable_error_instead_of_type_error(client, session):
    project = await ProjectRepository(session).create("u1", "name", "")
    response = await client.get(f"/api/factory/v1/projects/{project.id}/runs/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


async def test_real_execution_contract_carries_question_teacher_scores_and_negatives(column_context):
    import json

    seen = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": "kb",
                            "name": "KB",
                            "tenant_id": "tenant",
                            "embd_id": "embedding",
                            "tenant_embd_id": "embedder",
                            "vector_dim": 2,
                            "parser_id": "naive",
                            "doc_num": 2,
                            "chunk_num": 2,
                        }
                    ],
                },
            )
        body = json.loads(request.content)
        seen.append(body)
        if request.url.path.endswith("search:dense"):
            assert body["query"] == {"vector": [1, 0]}
            result = {"dim": 2, "hits": [{"chunk_id": "negative", "doc_id": "other", "score": 0.7}]}
        else:
            op = body["op"]
            if op == "chat":
                prompt = body["inputs"]["history"][0]["content"]
                result_body = (
                    {"overall": 9}
                    if prompt == "judge"
                    else {"question": "Which procedure applies?", "positives": ["positive"]}
                )
                output = {"text": json.dumps(result_body)}
            elif op == "embed_query":
                output = {"vector": [1, 0]}
            elif op == "rerank":
                assert body["inputs"] == {
                    "query": "Which procedure applies?",
                    "texts": ["Evidence positive", "Evidence negative"],
                }
                output = {"scores": [0.95, 0.2]}
            else:
                output = {"vectors": [[1, 0]]}
            result = {
                "outputs": output,
                "usage": {"total_tokens": 10},
                "latency_ms": 1,
                "model_fingerprint": "teacher-v1",
            }
        return httpx.Response(200, json={"code": 0, "data": result}, headers={"X-Gateway-Version": "1"})

    gateway = GatewayClient(GatewaySettings(), "u1", transport=httpx.MockTransport(handler))
    recipe = _recipe(
        [
            {"name": "negatives", "type": "processor", "params": {"kind": "hard_negative_select"}},
            {
                "name": "teacher_scores",
                "type": "rerank_score",
                "model": "teacher",
                "params": {"targets": ["qa.positives", "candidates"]},
            },
            {"name": "candidates", "type": "retrieval", "params": {}},
            {
                "name": "judge",
                "type": "llm_judge",
                "model": "judge",
                "prompt": "judge",
                "output_schema": {"required": ["overall"]},
            },
            {
                "name": "qa",
                "type": "llm_structured",
                "model": "generator",
                "prompt": "{{ seed.parts | render_parts }}",
                "output_schema": {"required": ["question", "positives"]},
            },
            {"name": "query_vector", "type": "embedding", "model": "embedder", "params": {"field": "qa.question"}},
        ],
        models={name: {"model_id": name} for name in ("generator", "judge", "teacher", "embedder")},
    )
    rows = await produce(recipe, [_segment("positive"), _segment("negative")], await column_context(gateway), 1, 1)
    assert rows[0]["negatives"] == ["negative"]
    assert rows[0]["judge"] == {"overall": 9}
    assert rows[0]["teacher_scores"]["model_fingerprint"] == "teacher-v1"
    assert all(gate["passed"] for gate in release_check(rows, "ready"))
    assert any(call.get("op") == "embed_documents" for call in seen)


async def test_export_reads_the_complete_frozen_corpus_and_teacher_scores(client, session):
    project = await ProjectRepository(session).create("u1", "name", "")
    session.add(
        SnapshotRow(id="snap", project_id=project.id, name="snapshot", status="ready", sources=[], created_by="u1")
    )
    session.add(
        RunRow(
            id="run", project_id=project.id, recipe_id="recipe", snapshot_id="snap", status="completed", user_id="u1"
        )
    )
    session.add(DatasetRow(id="ds", project_id=project.id, run_id="run", name="dataset", sample_count=1))
    for i in range(1026):
        session.add(
            SegmentRow(
                id=f"seg_{i:04}",
                snapshot_id="snap",
                origin_kb_id="kb",
                origin_doc_id="doc",
                origin_chunk_id=f"chunk_{i}",
                modality="text",
                parts=[{"type": "text", "text": f"passage {i}"}],
                title="document",
                position={},
                content_hash=f"hash_{i}",
                minhash=[],
                tokens=2,
                meta={},
            )
        )
    sample = {
        "row_key": "q",
        "query": "Question?",
        "split": "test",
        "positives": ["seg_0000"],
        "negatives": ["seg_1025"],
        "modality": "text",
        "teacher_scores": {"scores": {"seg_0000": 0.9, "seg_1025": 0.2}, "model_fingerprint": "teacher"},
    }
    session.add(ReleaseRow(id="rel", dataset_id="ds", status="released", sample_count=1, gates=[], samples=[sample]))
    await session.commit()
    path = f"/api/factory/v1/projects/{project.id}/releases/rel:export"
    response = await client.post(path, params={"adapter": "beir"})
    assert response.status_code == 200
    assert len(response.json()["files"]["corpus.jsonl"].splitlines()) == 1026
    response = await client.post(path, params={"adapter": "flagembedding"})
    assert response.status_code == 200
    assert '"neg": ["passage 1025"]' in response.json()["files"]["test.jsonl"]
    assert '"pos_scores": [0.9]' in response.json()["files"]["test.jsonl"]
