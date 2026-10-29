"""Offline checks for catalog pagination, mapping, and non-destructive reconciliation."""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "docker/scripts/sync_model_catalog.py"
spec = importlib.util.spec_from_file_location("sync_model_catalog", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
NOW = datetime(2026, 10, 27, tzinfo=sync.TZ)
POLICY = {"retirements": [], "token_limits": {"text-embedding-v4": 8192}}


def model(name="qwen3.8-flash", caps=None, limit=1000000):
    return {
        "model": name,
        "capabilities": caps or ["TG", "VU", "Reasoning"],
        "features": ["function-calling"],
        "inference_metadata": {"request_modality": ["Text", "Image"], "response_modality": ["Text"]},
        "model_info": {"context_window": limit, "max_input_tokens": None},
        "inference_offline_info": None,
    }


def catalog(*names):
    return {
        "factory_llm_infos": [
            {"name": sync.PROVIDER, "llm": [{"llm_name": n, "model_type": "chat", "max_tokens": 4096} for n in names]},
            {"name": "Other", "llm": [{"llm_name": "private", "model_type": "chat"}]},
        ]
    }


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class Session:
    def __init__(self, pages):
        self.pages = iter(pages)

    def get(self, *args, **kwargs):
        return Response(next(self.pages))


def page(number, total, names):
    return {"success": True, "output": {"page_no": number, "total": total, "models": [model(n) for n in names]}}


class CatalogTests(unittest.TestCase):
    def test_new_multimodal_model_keeps_context_not_output_budget(self):
        row, reason = sync._normalize(model(), POLICY, {})
        self.assertIsNone(reason)
        self.assertEqual(row["model_type"], ["chat", "image2text"])
        self.assertEqual(row["max_tokens"], 1000000)
        self.assertEqual(row["features"], ["thinking"])
        self.assertTrue(row["is_tools"])

    def test_rerank_is_not_embedding_even_with_same_official_capability(self):
        row, _ = sync._normalize(model("qwen3-rerank", ["TR"], 30000), POLICY, {})
        self.assertEqual(row["model_type"], ["rerank"])
        row, _ = sync._normalize(model("text-embedding-v4", ["TR"], None), POLICY, {})
        self.assertEqual((row["model_type"], row["max_tokens"]), (["embedding"], 8192))

    def test_unknown_vector_api_is_reported_not_guessed(self):
        row, reason = sync._normalize(model("new-vector-api", ["TR"]), POLICY, {})
        self.assertIsNone(row)
        self.assertIn("review", reason)

    def test_unsupported_generation_and_realtime_are_excluded(self):
        for name, caps in [("wan-image", ["IG"]), ("realtime", ["Realtime-Omni"]), ("qwen3-tts-flash", ["TTS"]), ("qwen-mt-plus", ["TG"])]:
            with self.subTest(name=name):
                self.assertIsNone(sync._normalize(model(name, caps), POLICY, {})[0])

    def test_missing_model_is_not_treated_as_retired(self):
        before = catalog("private-alias")
        after, report = sync._build_catalog(before, {"models": [model()]}, POLICY, NOW)
        self.assertIn("private-alias", report["retained_for_review"])
        self.assertEqual(report["remove"], [])
        self.assertEqual(before["factory_llm_infos"][1], after["factory_llm_infos"][1])
        self.assertEqual(len(before["factory_llm_infos"][0]["llm"]), 1)

    def test_future_retirement_stays_until_exact_deadline(self):
        item = model()
        item["inference_offline_info"] = {"offline_time": "2027-01-19 10:00:00"}
        _, report = sync._build_catalog(catalog(item["model"]), {"models": [item]}, POLICY, NOW)
        self.assertFalse(report["remove"])
        self.assertIn(item["model"], report["scheduled_retirements"])
        _, report = sync._build_catalog(catalog(item["model"]), {"models": [item]}, POLICY, datetime(2027, 1, 19, 10, tzinfo=sync.TZ))
        self.assertEqual(report["remove"], [item["model"]])

    def test_announced_retirement_removes_absent_model(self):
        policy = {**POLICY, "retirements": [{"effective_at": "2026-10-10", "models": ["qwen3-vl-flash"]}]}
        _, report = sync._build_catalog(catalog("qwen3-vl-flash"), {"models": [model()]}, policy, NOW)
        self.assertEqual(report["remove"], ["qwen3-vl-flash"])

    def test_complete_pagination(self):
        result = sync._fetch_pages(Session([page(1, 3, ["a", "b"]), page(2, 3, ["c"])]), "endpoint", "china")
        self.assertEqual(len(result["models"]), 3)

    def test_partial_repeated_and_changing_pages_fail_closed(self):
        for pages in [[page(1, 0, [])], [page(1, 3, ["a"]), page(2, 3, [])], [page(1, 2, ["a"]), page(2, 2, ["a"])], [page(1, 2, ["a"]), page(2, 3, ["b"])], [page(1, 2, ["a"]), page(1, 2, ["b"])]]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                sync._fetch_pages(Session(pages), "endpoint", "china")

    def test_bad_offline_schema_is_not_ignored(self):
        item = model()
        item["inference_offline_info"] = {"new_field": "unknown"}
        with self.assertRaises(TypeError):
            sync._build_catalog(catalog(), {"models": [item]}, POLICY, NOW)

    def test_existing_id_disabled_status_validation_and_extra_survive(self):
        instance = {"id": "instance", "provider_id": "provider"}
        original = {
            "id": "keep-id",
            "model_name": "qwen3.8-flash",
            "instance_id": "instance",
            "provider_id": "provider",
            "model_type": 1,
            "status": "0",
            "extra": json.dumps({"verify": "passed", "custom": 123}),
            "create_time": 1,
            "create_date": "2020-01-01",
            "update_time": 1,
            "update_date": "2020-01-01",
        }
        row = sync._normalize(model(), POLICY, {})[0]
        result = sync._plan_rows([original], [row], [], instance, NOW)
        self.assertEqual((result[0]["id"], result[0]["status"], result[0]["create_time"]), ("keep-id", "0", 1))
        self.assertEqual(json.loads(result[0]["extra"])["custom"], 123)
        self.assertEqual(json.loads(result[0]["extra"])["verify"], "passed")
        self.assertEqual(sync._plan_rows(result, [row], [], instance, NOW), result)

    def test_new_rows_are_unverified_and_custom_rows_are_preserved(self):
        instance = {"id": "instance", "provider_id": "provider"}
        desired = sync._normalize(model(), POLICY, {})[0]
        rows = sync._plan_rows([], [desired], [], instance, NOW)
        self.assertEqual(rows[0]["status"], "active")
        self.assertEqual(json.loads(rows[0]["extra"])["verify"], "unknown")
        self.assertEqual(sync._plan_rows(rows, [], [], instance, NOW), rows)

    def test_repeated_catalog_build_is_stable(self):
        first, _ = sync._build_catalog(catalog(), {"models": [model()]}, POLICY, NOW)
        second, report = sync._build_catalog(first, {"models": [model()]}, POLICY, NOW)
        self.assertEqual(first, second)
        self.assertEqual((report["add"], report["update"], report["remove"]), ([], [], []))

    def test_unconfirmed_registration_metadata_is_not_overwritten(self):
        instance = {"id": "instance", "provider_id": "provider"}
        desired = sync._normalize(model(), POLICY, {})[0]
        rows = sync._plan_rows([], [desired], [], instance, NOW)
        rows[0]["extra"] = json.dumps({"custom": "manual", "max_tokens": 42})
        result = sync._plan_rows(rows, [desired], [], instance, NOW, [desired["llm_name"]])
        self.assertEqual(rows, result)


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "conf").mkdir()
        (self.root / "docker/config").mkdir(parents=True)
        self.work = self.root / "run"
        self.work.mkdir()
        self.catalog = self.root / "conf/llm_factories.json"
        self.catalog.write_bytes(b"before")
        policy = b"policy"
        (self.root / "docker/config/tongyi-sync-policy.json").write_bytes(policy)
        (self.work / "catalog.before.json").write_bytes(b"before")
        (self.work / "catalog.after.json").write_bytes(b"after")
        self.before_rows, self.after_rows = [{"id": "old"}], [{"id": "old"}, {"id": "new"}]
        plan = {
            "created_at": datetime.now(sync.TZ).isoformat(),
            "instance": {"id": "instance"},
            "before_sha256": sync._sha(b"before"),
            "after_sha256": sync._sha(b"after"),
            "policy_sha256": sync._sha(policy),
            "before_rows": self.before_rows,
            "after_rows": self.after_rows,
            "report": {"scheduled_retirements": {}},
        }
        (self.work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(sync, "ROOT", self.root).start()
        self.reload = patch.object(sync, "_reload").start()

    def run_action(self, action, worker):
        with patch.object(sys, "argv", ["sync", action, "--work-dir", str(self.work)]), patch.object(sync, "_call", side_effect=worker):
            sync.main()

    def test_stale_file_refuses_before_database_mutation(self):
        self.catalog.write_bytes(b"user edit")
        actions = []

        def worker(container, action, payload):
            actions.append(action)
            return {"idle": True}

        with self.assertRaisesRegex(ValueError, "Host catalog changed"):
            self.run_action("apply", worker)
        self.assertEqual(actions, ["idle"])
        self.assertEqual(self.catalog.read_bytes(), b"user edit")
        self.reload.assert_not_called()

    def test_database_conflict_does_not_publish_file_or_restart(self):
        def worker(container, action, payload):
            if action == "replace":
                self.assertEqual(payload["expected"], self.before_rows)
                raise RuntimeError("Database changed")
            return {"idle": True}

        with self.assertRaisesRegex(RuntimeError, "Database changed"):
            self.run_action("apply", worker)
        self.assertEqual(self.catalog.read_bytes(), b"before")
        self.reload.assert_not_called()

    def test_rollback_refuses_concurrent_database_edit(self):
        self.catalog.write_bytes(b"after")

        def worker(container, action, payload):
            self.assertNotEqual(action, "replace")
            return {"rows": [{"id": "user-added"}]} if action == "read" else {"idle": True}

        with self.assertRaisesRegex(ValueError, "refusing rollback"):
            self.run_action("rollback", worker)
        self.assertEqual(self.catalog.read_bytes(), b"after")

    def test_rollback_restores_original_rows_and_catalog(self):
        self.catalog.write_bytes(b"after")
        replacements = []

        def worker(container, action, payload):
            if action == "read":
                return {"rows": self.after_rows}
            if action == "replace":
                replacements.append(payload)
            return {}

        self.run_action("rollback", worker)
        self.assertEqual(replacements[0]["target"], self.before_rows)
        self.assertEqual(self.catalog.read_bytes(), b"before")
        self.reload.assert_called_once()

    def test_retry_rollback_reloads_even_after_files_and_rows_were_restored(self):
        def worker(container, action, payload):
            return {"rows": self.before_rows} if action == "read" else {}

        self.reload.side_effect = RuntimeError("health timeout")
        with self.assertRaisesRegex(RuntimeError, "health timeout"):
            self.run_action("rollback", worker)
        self.assertEqual(json.loads((self.work / "operation.json").read_text())["phase"], "catalog_complete")
        self.reload.side_effect = None
        self.run_action("rollback", worker)
        self.assertEqual(self.reload.call_count, 2)
        self.assertEqual(json.loads((self.work / "operation.json").read_text())["phase"], "complete")


if __name__ == "__main__":
    unittest.main()
