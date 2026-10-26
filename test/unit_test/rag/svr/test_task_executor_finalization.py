"""Exercise the task handler without importing model runtimes or connecting to storage."""

import ast
import asyncio
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.constants import PipelineTaskType
from common.exceptions import TaskCanceledException


def _handler(*, execution_error=None, log_error=None):
    path = Path(__file__).resolve().parents[4] / "rag/svr/task_executor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_task")
    task = {"id": "task", "task_type": "structure_graph", "doc_id": "graph_raptor_x", "doc_ids": ["doc"]}
    message = MagicMock()
    record = MagicMock(side_effect=log_error)
    namespace = {
        "asyncio": asyncio,
        "copy": copy,
        "json": json,
        "logging": logging,
        "os": SimpleNamespace(environ={}),
        "exceptiongroup": SimpleNamespace(ExceptionGroup=ExceptionGroup),
        "collect": AsyncMock(return_value=(message, task)),
        "DONE_TASKS": 0,
        "FAILED_TASKS": 0,
        "CURRENT_TASKS": {},
        "TASK_TYPE_TO_PIPELINE_TASK_TYPE": {"structure_graph": PipelineTaskType.STRUCTURE_GRAPH},
        "PipelineTaskType": PipelineTaskType,
        "TaskCanceledException": TaskCanceledException,
        "_KB_FANOUT_TASK_TYPES": ["structure_graph"],
        "_redact_task_user": lambda value: value,
        "normalize_llm_user_id": lambda value: value,
        "set_llm_request_context": MagicMock(),
        "reset_llm_request_context": MagicMock(),
        "set_recording_context": MagicMock(),
        "NullRecordingContext": MagicMock(),
        "get_recording_context": MagicMock(),
        "TaskManager": SimpleNamespace(run_refactored_task=AsyncMock(side_effect=execution_error)),
        "PipelineOperationLogService": SimpleNamespace(record_pipeline_operation=record),
        "set_progress": MagicMock(),
        "has_canceled": MagicMock(),
        **dict.fromkeys(["chat_limiter", "minio_limiter", "chunk_limiter", "embed_limiter", "kg_limiter"]),
    }
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102 -- execute only the checked-in handler AST
    return namespace, message, record


@pytest.mark.parametrize("log_error", [None, RuntimeError("operation log unavailable")])
def test_processed_task_acknowledged_even_when_operation_log_fails(log_error):
    namespace, message, record = _handler(log_error=log_error)
    assert asyncio.run(namespace["handle_task"]()) is True
    message.ack.assert_called_once()
    assert namespace["DONE_TASKS"] == 1
    record.assert_called_once()


def test_failed_execution_is_recorded_and_acknowledged():
    namespace, message, _ = _handler(execution_error=ValueError("execution failed"))
    assert asyncio.run(namespace["handle_task"]()) is True
    assert namespace["FAILED_TASKS"] == 1
    assert namespace["set_progress"].call_args.kwargs["prog"] == -1
    message.ack.assert_called_once()


def test_shutdown_cancellation_does_not_ack_unfinished_work():
    namespace, message, _ = _handler(execution_error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(namespace["handle_task"]())
    message.ack.assert_not_called()
