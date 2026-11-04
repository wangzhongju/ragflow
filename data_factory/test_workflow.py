"""Isolated REST acceptance tests. No model, live tenant or RAGFlow database needed."""

import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from flask import Flask, request
from werkzeug.serving import make_server


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.api = Flask("fixture")
        cls.allowed = True
        cls.block = False
        cls.reading = threading.Event()
        cls.release = threading.Event()
        cls.calls = []
        cls.content = "Isolate the motor supply."

        @cls.api.get("/users/me")
        def who():
            key = request.headers.get("Authorization")
            if key not in ("Bearer alice", "Bearer bob"):
                return {"code": 401}, 401
            return {"code": 0, "data": {"id": key.split()[1]}}

        @cls.api.get("/tenants/alice/users")
        def members():
            return {"code": 0, "data": [{"user_id": "bob", "role": "normal"}]}

        @cls.api.get("/tenants")
        def tenants():
            return {"code": 0, "data": [{"tenant_id": "alice", "role": "normal"}]}

        @cls.api.get("/datasets/k/documents")
        def documents():
            if not cls.allowed:
                return {"code": 102}, 400
            return {"code": 0, "data": {"docs": [{"id": i} for i in request.args.getlist("ids")]}}

        @cls.api.get("/datasets/k/documents/<doc>/chunks")
        def chunks(doc):
            cls.calls.append((doc, dict(request.args)))
            if not cls.allowed:
                return {"code": 102}, 400
            size = int(request.args.get("page_size", 100))
            if size > 100:
                return {"code": 400}, 400
            if cls.block and doc == "b" and size > 1:
                cls.reading.set()
                cls.release.wait(10)
            total = 1025 if doc == "a" else 2
            start = (int(request.args.get("page", 1)) - 1) * size
            rows = [
                {
                    "id": str(i),
                    "document_id": doc,
                    "available": True,
                    "doc_type_kwd": "text",
                    "content": cls.content if i % 2 == 0 else "Inspect the gasket.",
                    "questions": ["How do I disconnect power?" if i % 2 == 0 else "What needs inspection?"],
                }
                for i in range(start, min(start + size, total))
            ]
            if request.args.get("id"):
                rows = [r for r in rows if r["id"] == request.args["id"]]
            return {"code": 0, "data": {"doc": {"name": "manual.txt", "run": "DONE"}, "total": total, "chunks": rows}}

        @cls.api.get("/datasets/k/documents/<doc>")
        def original(doc):
            return b"Test fixture original.", 200, {"Content-Type": "text/plain"}

        @cls.api.get("/models")
        def models():
            return {"code": 0, "data": [{"model_id": "chat-fixture", "model_type": ["chat"]}]}

        @cls.api.post("/data-factory-model/generate")
        def generate():
            data = request.json
            if "evidence_ids" in data["prompt"]:
                evidence = json.loads(data["prompt"].split("\n", 1)[1])["evidence_ids"]
                answer = {"answer": "Disconnect the supply before inspection.", "evidence_ids": evidence}
            else:
                answer = ["How should the motor supply be isolated?"]
            return {"code": 0, "data": {"text": json.dumps(answer), "model_name": "fixture"}}

        server = make_server("127.0.0.1", 0, cls.api, threaded=True)
        cls.server = server
        cls.thread = threading.Thread(target=server.serve_forever, daemon=True)
        cls.thread.start()
        cls.env = patch.dict(
            os.environ,
            FACTORY_DB=str(Path(cls.tmp.name) / "test.sqlite"),
            FACTORY_ASSET_DIR=str(Path(cls.tmp.name) / "objects"),
            FACTORY_MINIO_ENDPOINT="",
            RAGFLOW_API=f"http://127.0.0.1:{server.server_port}",
        )
        cls.env.start()
        from .app import app

        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.release.set()
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.env.stop()
        cls.tmp.cleanup()

    def api_call(self, path, body=None, status=200, token="alice"):
        method = self.client.get if body is None else self.client.post
        r = method("/api/v1/data-factory" + path, headers={"Authorization": "Bearer " + token}, json=body)
        self.assertEqual(r.status_code, status, r.get_data()[:300])
        return r

    def wait_for(self, path, state):
        for _ in range(150):
            result = self.api_call(path).json
            if result["state"] == state:
                return result
            if result["state"] == "failed":
                self.fail(result["error"])
            time.sleep(0.1)
        self.fail("job timeout")

    def test_capture_review_export_and_recovery(self):
        cls = type(self)
        cls.block = True
        ds = str(uuid.uuid4())
        body = {"name": "fixture", "sources": [["k", "a"], ["k", "b"]], "request_id": ds}
        path = "/datasets/" + ds
        self.api_call("/datasets", body, 202)
        self.api_call("/datasets", body)
        self.api_call("/datasets", dict(body, name="conflict"), 409)
        self.assertTrue(cls.reading.wait(8))
        self.api_call(path + "/jobs/cancel", {})
        cls.release.set()
        cls.block = False
        self.assertEqual(self.api_call(path).json["state"], "cancelled")
        self.api_call(path + "/jobs/retry", {}, 202)
        info = self.wait_for(path, "ready")
        doc_pages = [args for doc, args in cls.calls if doc == "a" and args.get("page") == "11"]
        self.assertEqual(len(doc_pages), 2, "checkpoint should avoid a third capture")
        self.assertEqual(info["captured"], 2)
        self.api_call(path, status=404, token="bob")
        self.api_call(path + "/members", {"user": "bob", "role": "reviewer"})
        self.api_call(path, token="bob")
        self.api_call(path + "/versions", {}, 403, token="bob")
        rows = self.api_call(path + "/samples").json
        self.assertEqual(len(rows), 2)
        review = path + "/samples/" + str(rows[0]["id"]) + "/review"
        self.api_call(path + "/versions", {}, 400)
        self.api_call(review, {"status": "approved", "revision": 1, "payload": dict(rows[0]["sample"]["payload"], negatives=[])}, 400)
        self.api_call(review, {"status": "approved", "revision": 1}, token="bob")
        self.api_call(review, {"status": "approved", "revision": 1}, 409)
        version = self.api_call(path + "/versions", {}).json["version"]
        url = path + "/versions/" + version + "/download"
        blob = self.api_call(url).data
        self.api_call(url, status=403, token="bob")
        self.api_call(path + "/members", {"user": "bob", "role": "publisher"})
        self.assertEqual(blob, self.api_call(url, token="bob").data)
        self.api_call(path + "/members", {"user": "bob", "role": "remove"})
        self.api_call(url, status=404, token="bob")
        self.api_call(review, {"status": "rejected", "revision": 2, "reason": "fixture"})
        cls.content = "Changed upstream."
        self.assertEqual(blob, self.api_call(url).data)
        with ZipFile(io.BytesIO(blob)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            batch = []
            for name, metadata in manifest["files"].items():
                content = archive.read(name)
                self.assertEqual(hashlib.sha256(content).hexdigest(), metadata["sha256"])
                if name in ("train.jsonl", "validation.jsonl", "test.jsonl"):
                    batch.extend(json.loads(line) for line in content.splitlines())
            self.assertEqual(len(batch), 1)
            self.assertTrue(batch[0]["payload"]["positives"] and batch[0]["payload"]["negatives"])
            self.assertNotIn(cls.content, batch[0]["payload"]["positives"])
        cls.allowed = False
        try:
            self.api_call(url, status=403)
            self.assertEqual(self.api_call("/datasets").json, [])
        finally:
            cls.allowed = True

    def test_health_and_auth(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/data-factory/datasets").status_code, 401)
        self.api_call("/datasets", status=403, token="invalid")

    def test_interrupted_job_reuses_checkpoint(self):
        from .store import initialize

        cls = type(self)
        cls.block = True
        cls.reading.clear()
        cls.release.clear()
        ds = str(uuid.uuid4())
        path = "/datasets/" + ds
        self.api_call("/datasets", {"name": "recovery", "sources": [["k", "a"], ["k", "b"]], "request_id": ds}, 202)
        try:
            self.assertTrue(cls.reading.wait(10))
            initialize()
            self.assertEqual(self.api_call(path).json["state"], "interrupted")
            self.api_call(path + "/jobs/retry", {}, 202)
        finally:
            cls.block = False
            cls.release.set()
        self.assertEqual(self.wait_for(path, "ready")["captured"], 2)
        response = self.client.delete("/api/v1/data-factory" + path, headers={"Authorization": "Bearer alice"})
        self.assertEqual(response.status_code, 200)
        self.api_call(path, status=404)

    def test_independent_generators_and_budget(self):
        for task in ("reranker", "llm"):
            with self.subTest(task=task):
                ds = str(uuid.uuid4())
                path = "/datasets/" + ds
                config = {"max_samples": 1, "query_mode": "existing", "model_id": "chat-fixture"} if task == "llm" else {"max_samples": 1}
                self.api_call("/datasets", {"request_id": ds, "name": task, "task": task, "sources": [["k", "b"]], "config": config}, 202)
                info = self.wait_for(path, "ready")
                row = self.api_call(path + "/samples").json[0]
                payload = row["sample"]["payload"]
                if task == "reranker":
                    self.api_call(path + "/samples/1/review", {"revision": 1, "status": "approved"}, 400)
                    for candidate in payload["candidates"]:
                        if candidate["label"] is None:
                            candidate["label"] = 0
                self.api_call(path + "/samples/1/review", {"revision": 1, "status": "approved", "payload": payload})
                version = self.api_call(path + "/versions", {}).json["version"]
                adapter = "messages-v1" if task == "llm" else "reranker-pointwise-v1"
                blob = self.api_call(path + "/versions/" + version + "/download?adapter=" + adapter).data
                self.assertIn("manifest.json", ZipFile(io.BytesIO(blob)).namelist())
                self.assertEqual(info["calls"], 1 if task == "llm" else 0)
        ds = str(uuid.uuid4())
        path = "/datasets/" + ds
        self.api_call("/datasets", {"request_id": ds, "name": "budget", "sources": [["k", "b"]], "config": {"query_mode": "llm", "model_id": "chat-fixture", "max_calls": 0}}, 202)
        for _ in range(50):
            info = self.api_call(path).json
            if info["state"] == "failed":
                break
            time.sleep(0.1)
        self.assertEqual(info["state"], "failed")
        self.assertEqual(info["calls"], 0)

    def test_multimodal_export_and_quality_boundaries(self):
        from . import assets
        from .source import canonical
        from .store import database

        ds = str(uuid.uuid4())
        path = "/datasets/" + ds
        self.api_call("/datasets", {"request_id": ds, "name": "media", "sources": [["k", "b"]], "config": {"max_samples": 1}}, 202)
        self.wait_for(path, "ready")
        row = self.api_call(path + "/samples").json[0]
        with database(True) as db:
            sha = assets.register(db, "alice", b"fixture-media", "image/png", "fixture.png")
            self.assertEqual(sha, assets.register(db, "alice", b"fixture-media", "image/png", "duplicate.png"))
            assets.relate(db, ds, "alice", sha, "b", "image")
            eid = row["sample"]["payload"]["positives"][0]
            evidence = row["evidence"][eid]
            evidence["parts"].append({"type": "image", "asset_id": sha})
            db.execute("UPDATE evidence SET body=? WHERE dataset=? AND id=?", (canonical(evidence), ds, eid))
            self.assertNotIn("data", {c[1] for c in db.execute("PRAGMA table_info(asset)")})
        payload = row["sample"]["payload"]
        invalid = dict(payload, negatives=[{"evidence_id": eid, "method": "manual"}])
        self.api_call(path + "/samples/1/review", {"revision": 1, "status": "approved", "payload": invalid}, 400)
        invalid = dict(payload, query=[{"type": "image", "asset_id": "0" * 64}])
        self.api_call(path + "/samples/1/review", {"revision": 1, "status": "draft", "payload": invalid}, 400)
        self.api_call(path + "/samples/1/review", {"revision": 1, "status": "draft", "payload": {"messages": []}}, 400)
        self.api_call(path + "/samples/1/review", {"revision": 1, "status": "approved"})
        version = self.api_call(path + "/versions", {}).json["version"]
        url = path + "/versions/" + version + "/download"
        self.api_call(url + "?adapter=sentence-transformers-triplet-v1", status=400)
        blob = self.api_call(url).data
        with ZipFile(io.BytesIO(blob)) as archive:
            self.assertIn("assets/" + sha + ".png", archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            for name, meta in manifest["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), meta["sha256"])
