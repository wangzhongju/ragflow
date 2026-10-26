import importlib.util
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from common.constants import PipelineTaskType


@pytest.mark.parametrize(
    ("task_type", "task_field", "current_task_id"),
    [
        (PipelineTaskType.STRUCTURE_GRAPH, "structure_graph_task_id", "task"),
        (PipelineTaskType.STRUCTURE_GRAPH, "graphrag_task_id", "task"),
        (PipelineTaskType.STRUCTURE_MINDMAP, "structure_mindmap_task_id", "task"),
        (PipelineTaskType.STRUCTURE_MINDMAP, "mindmap_task_id", "task"),
        (PipelineTaskType.TIMELINE, "timeline_task_id", "task"),
        (PipelineTaskType.SESSION_GRAPH, "session_graph_task_id", "task"),
        (PipelineTaskType.SESSION_ESSENCE, "session_essence_task_id", "task"),
        (PipelineTaskType.STRUCTURE, "structure_task_id", "task"),
        (PipelineTaskType.STRUCTURE_GRAPH, "graphrag_task_id", "newer-task"),
    ],
)
def test_completed_structure_task_records_operation_without_external_services(monkeypatch, task_type, task_field, current_task_id):
    now = datetime(2026, 10, 23, 14, 0)
    document = SimpleNamespace(
        id="doc",
        kb_id="kb",
        parser_id="naive",
        thumbnail="",
        name="test.pdf",
        run="1",
        progress=0.2,
        progress_msg="parsing",
        process_begin_at=now,
        process_duration=10,
        suffix="pdf",
        type="pdf",
        source_type="local",
    )
    task = SimpleNamespace(progress=1, progress_msg="Built graph", begin_at=now, process_duration=120)
    model = MagicMock()
    model.select.return_value.where.return_value.count.return_value = 0
    kb_service = SimpleNamespace(get_by_id=lambda _: (True, SimpleNamespace(tenant_id="tenant", **{task_field: current_task_id})), update_by_id=MagicMock())
    db = SimpleNamespace(connection_context=lambda: lambda fn: fn, atomic=nullcontext)
    modules = {
        "peewee": {"fn": MagicMock()},
        "api.db.db_models": {"DB": db, "Document": MagicMock(), "PipelineOperationLog": model},
        "api.db.services.canvas_service": {"UserCanvasService": MagicMock()},
        "api.db.services.common_service": {"CommonService": object},
        "api.db.services.document_service": {"DocumentService": SimpleNamespace(get_by_id=lambda _: (True, document))},
        "api.db.services.knowledgebase_service": {"KnowledgebaseService": kb_service},
        "api.db.services.task_service": {"GRAPH_RAPTOR_FAKE_DOC_ID": "graph_raptor_x", "TaskService": SimpleNamespace(get_by_id=lambda _: (True, task))},
        "common.misc_utils": {"get_uuid": lambda: "operation-log-id"},
        "common.time_utils": {"current_timestamp": lambda: 1, "datetime_format": lambda value: value},
    }
    for name in ["api", "api.db", "api.db.services"]:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    for name, attrs in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[5] / "api/db/services/pipeline_operation_log_service.py"
    spec = importlib.util.spec_from_file_location("graph_operation_completion_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = MagicMock(return_value="saved")
    monkeypatch.setattr(module.PipelineOperationLogService, "save", saved)
    result = module.PipelineOperationLogService.create("graph_raptor_x", "", task_type, task_id="task", referred_document_id="doc")
    assert result == "saved"
    assert saved.call_args.kwargs["task_type"] == task_type
    assert saved.call_args.kwargs["progress"] == 1
    assert saved.call_args.kwargs["operation_status"] == "3"
    if current_task_id == "task":
        from datetime import timedelta

        kb_service.update_by_id.assert_called_once_with("kb", {task_field.removesuffix("_id") + "_finish_at": now + timedelta(seconds=120)})
    else:
        kb_service.update_by_id.assert_not_called()
