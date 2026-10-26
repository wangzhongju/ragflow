import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from common.exceptions import TaskCanceledException


@pytest.fixture
def pipeline(monkeypatch):
    class Graph:
        def __init__(self, dsl, *_args):
            self.components = json.loads(dsl)["components"]
            self.task_id = "task"

        def get_component_name(self, name):
            return name

    class Redis:
        def __init__(self):
            self.cache = {}
            self.unavailable = False

        def get(self, key):
            if self.unavailable:
                raise ConnectionError("Redis unavailable")
            return self.cache.get(key)

        def set_obj(self, key, value, _ttl):
            self.cache[key] = json.dumps(value)

    redis = Redis()
    updates = []
    state = SimpleNamespace(canceled=False)
    modules = {
        "agent.canvas": {"Graph": Graph},
        "api.db.services.document_service": {"DocumentService": SimpleNamespace(get_knowledgebase_id=lambda _: "kb")},
        "api.db.services.task_service": {
            "TaskService": SimpleNamespace(update_progress=lambda _id, info: updates.append(info)),
            "has_canceled": lambda _: state.canceled,
            "CANVAS_DEBUG_DOC_ID": "debug",
        },
        "rag.utils.redis_conn": {"REDIS_CONN": redis},
    }
    for name in ["agent", "api", "api.db", "api.db.services", "rag", "rag.utils"]:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    for name, attrs in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[4] / "rag/flow/pipeline.py"
    spec = importlib.util.spec_from_file_location("pipeline_progress_test_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    instance = module.Pipeline({"components": dict.fromkeys(["File", "Parser", "Chunker", "Extractor", "Compiler", "Indexer"])}, doc_id="doc", task_id="task", flow_id="flow")
    return instance, updates, redis, state


def test_progress_survives_trace_expiry_between_pdf_batches(pipeline):
    instance, updates, redis, _ = pipeline
    instance.callback("File", 1, "Done")
    instance.callback("Parser", 0.04, "Start")
    assert updates[-1]["progress"] == pytest.approx(1.04 / 6)
    redis.cache.clear()  # The first 50-page batch took longer than the trace TTL.
    instance.callback("Parser", 50 / 146, "Structured: 50/146 pages")
    assert updates[-1]["progress"] == pytest.approx((1 + 50 / 146) / 6)
    redis.cache.clear()
    instance.callback("Parser", 100 / 146, "Structured: 100/146 pages")
    assert updates[-1]["progress"] == pytest.approx((1 + 100 / 146) / 6)


def test_numeric_only_callbacks_advance_without_empty_trace_lines(pipeline):
    instance, updates, redis, _ = pipeline
    instance.callback("Parser", 0.6)
    assert updates[-1] == {"progress": pytest.approx(0.1), "progress_msg": ""}
    assert redis.cache == {}


def test_redis_trace_failure_does_not_prevent_task_progress(pipeline):
    instance, updates, redis, _ = pipeline
    redis.unavailable = True
    instance.callback("File", 1, "Done")
    assert updates[-1]["progress"] == pytest.approx(1 / 6)


def test_repeated_or_out_of_order_component_callbacks_do_not_double_count(pipeline):
    instance, updates, _, _ = pipeline
    instance.callback("File", 1, "Done")
    instance.callback("Parser", 0.8, "Table analysis")
    instance.callback("Parser", 0.3, "Late OCR callback")
    instance.callback("File", 1, "Done again")
    instance.callback("Parser", None, "Still processing")
    assert updates[-1]["progress"] == pytest.approx(1.8 / 6)


def test_failure_remains_terminal_after_trace_expiry(pipeline):
    instance, updates, redis, _ = pipeline
    instance.callback("Parser", -1, "Failed")
    redis.cache.clear()
    instance.callback("Indexer", 0.5, "Late callback")
    assert updates[-1]["progress"] == -1


def test_cancellation_is_not_hidden_by_empty_message_or_trace_failure(pipeline):
    instance, updates, redis, state = pipeline
    redis.unavailable = True
    state.canceled = True
    with pytest.raises(TaskCanceledException):
        instance.callback("Parser", 0.5)
    assert updates[-1]["progress"] == -1


def test_completed_components_reach_one(pipeline):
    instance, updates, _, _ = pipeline
    for component in instance.components:
        instance.callback(component, 1, "Done")
    assert updates[-1]["progress"] == 1
