"""A released package freezes provenance and verifies every payload byte."""

import hashlib
import io
import json
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from datafactory.release.package import build_archive
from datafactory.store.projects import ProjectRepository
from datafactory.store.tables import AuditRow, DatasetRow, RecipeVersionRow, RunRow, SampleRow, SegmentRow, SnapshotRow


async def _dataset(session, *, stale=False):
    project = await ProjectRepository(session).create("u1", "Release", "")
    session.add(
        SnapshotRow(
            id="snap",
            project_id=project.id,
            name="Frozen",
            status="stale" if stale else "ready",
            sources=[],
            created_by="u1",
        )
    )
    session.add(RecipeVersionRow(id="version", recipe_id="recipe", number=1, config={"frozen": True}))
    session.add(
        RunRow(
            id="run",
            project_id=project.id,
            recipe_id="recipe",
            snapshot_id="snap",
            recipe_version_id="version",
            status="completed",
        )
    )
    session.add(DatasetRow(id="dataset", project_id=project.id, run_id="run", name="Data", sample_count=1))
    body = {
        "row_key": "p",
        "query": "What is evidence?",
        "positives": ["p"],
        "negatives": ["n"],
        "split": "test",
        "modality": "text",
        "judge": {"overall": 8},
        "group_key": "doc",
    }
    session.add(
        SampleRow(
            id="sample",
            dataset_id="dataset",
            query=body["query"],
            positives=["p"],
            negatives=["n"],
            split="test",
            modality="text",
            review_status="approved",
            body=body,
        )
    )
    for name in ("p", "n"):
        session.add(
            SegmentRow(
                id=name,
                snapshot_id="snap",
                origin_kb_id="kb",
                origin_doc_id=name,
                origin_chunk_id=name,
                modality="text",
                parts=[{"type": "text", "text": f"Evidence {name}"}],
                title=name,
                position={},
                content_hash=name,
                minhash=[],
                tokens=2,
                meta={},
            )
        )
    await session.commit()
    return f"/api/factory/v1/projects/{project.id}"


async def test_release_zip_is_stable_and_independently_verifiable(client, session):
    prefix = await _dataset(session)
    created = await client.post(f"{prefix}/datasets/dataset/releases")
    assert created.status_code == 201, created.text
    release = created.json()
    assert release["manifest"]["recipe"] == {"frozen": True}
    assert release["manifest"]["approved_sample_ids"] == ["sample"]
    url = f"{prefix}/releases/{release['id']}/package?adapter=beir"
    downloaded = await client.get(url)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == (await client.get(url)).content
    with ZipFile(io.BytesIO(downloaded.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["adapter"] == "beir"
        assert archive.read("data/qrels/test.tsv") == b"query-id\tcorpus-id\tscore\np\tp\t1\n"
        for name, meta in manifest["files"].items():
            data = archive.read(name)
            assert len(data) == meta["size"] and hashlib.sha256(data).hexdigest() == meta["sha256"]
        for line in archive.read("SHA256SUMS").decode().splitlines():
            digest, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    # Decisions after release do not mutate its frozen content or provenance.
    await client.post(f"{prefix}/samples/sample/reviews", json={"decision": "rejected", "reason": "Later review"})
    assert (await client.get(url)).content == downloaded.content
    audit = await session.scalar(select(AuditRow).where(AuditRow.target_id == release["id"]))
    assert audit is not None and audit.action == "release_created"


async def test_warning_requires_explicit_reason_and_is_frozen(client, session):
    prefix = await _dataset(session, stale=True)
    url = f"{prefix}/datasets/dataset/releases"
    refused = await client.post(url)
    assert refused.status_code == 409 and refused.json()["code"] == "warning_ack_required"
    accepted = await client.post(url, json={"warning_reason": "Validated this frozen document edition"})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["manifest"]["warning_reason"] == "Validated this frozen document edition"


@pytest.mark.parametrize("name", ["../outside", "/absolute", "data/../../outside", "data\\outside"])
def test_archive_rejects_paths_outside_the_package(name):
    manifest = {"release_id": "r", "sample_count": 1, "snapshot_id": "s", "recipe_version_id": "v", "gates": []}
    with pytest.raises(ValueError, match="within the archive"):
        build_archive(manifest, "canonical", {name: b"bad"})
