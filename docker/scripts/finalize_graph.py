"""Finalize one completed StructureGraph task; read-only unless --apply is passed.

Run in the patched application image. Back up MySQL before applying; see
 docs/troubleshooting.md. This script never rebuilds a graph or deletes a stream.
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests
import valkey


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--queue", default="te.0.common", choices=["te.0.common", "te.1.common"])
    parser.add_argument("--backup", help="Private JSON path for the exact queue message; required with --apply")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup and a prior MySQL backup")

    from api.db.db_models import PipelineOperationLog
    from api.db.services.document_service import DocumentService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.pipeline_operation_log_service import PipelineOperationLogService
    from api.db.services.task_service import GRAPH_RAPTOR_FAKE_DOC_ID, TaskService
    from common.constants import PipelineTaskType

    env = os.environ
    redis = valkey.Valkey(host=env["REDIS_HOST"], port=6379, password=env["REDIS_PASSWORD"], db=1, decode_responses=True, socket_timeout=10)
    group = "rag_flow_svr_task_broker"
    rows = redis.xrange(args.queue, args.message_id, args.message_id)
    if len(rows) != 1:
        raise RuntimeError("Exact stream message not found")
    body = json.loads(rows[0][1]["message"])
    if body.get("id") != args.task_id or body.get("task_type") != "structure_graph":
        raise RuntimeError("Message does not match the requested StructureGraph task")
    ok, task = TaskService.get_by_id(args.task_id)
    if not ok or task.progress != 1 or task.task_type != "structure_graph" or task.doc_id != GRAPH_RAPTOR_FAKE_DOC_ID:
        raise RuntimeError("Task is not a successfully completed dataset graph")
    for worker in redis.smembers("TASKEXE"):
        latest = redis.zrevrange(worker, 0, 0, withscores=True)
        if latest and time.time() - latest[0][1] < 120 and args.task_id in (json.loads(latest[0][0]).get("current") or {}):
            raise RuntimeError("Task is still reported active by a live worker")
    doc_id = (body.get("doc_ids") or [None])[0]
    ok, doc = DocumentService.get_by_id(doc_id)
    if not ok or doc.kb_id != args.dataset_id:
        raise RuntimeError("Referenced document/dataset mismatch")
    ok, kb = KnowledgebaseService.get_by_id(doc.kb_id)
    if not ok or args.task_id not in (kb.graphrag_task_id, kb.structure_graph_task_id):
        raise RuntimeError("Dataset does not reference this graph task")
    for participant in body.get("doc_ids", []):
        found, participant_doc = DocumentService.get_by_id(participant)
        if not found or participant_doc.kb_id != kb.id:
            raise RuntimeError("A participating document belongs to another dataset")
    response = requests.post(
        f"http://{env['ES_HOST']}:9200/ragflow_{kb.tenant_id}/_count",
        auth=("elastic", env["ELASTIC_PASSWORD"]),
        json={"query": {"bool": {"filter": [{"term": {"kb_id": kb.id}}, {"term": {"scope_kwd": "dataset"}}, {"terms": {"knowledge_graph_kwd": ["entity", "relation"]}}]}}},
        timeout=20,
    )
    response.raise_for_status()
    graph_rows = response.json()["count"]
    if not graph_rows:
        raise RuntimeError("No dataset graph entities/relations; inspect output before recovery")
    lookup = (PipelineOperationLog.kb_id == kb.id) & (PipelineOperationLog.task_type == PipelineTaskType.STRUCTURE_GRAPH) & (PipelineOperationLog.process_begin_at == task.begin_at)
    pending = redis.xpending_range(args.queue, group, args.message_id, args.message_id, 1)
    report = {
        "task_id": task.id,
        "progress": task.progress,
        "dataset_graph_rows": graph_rows,
        "pending": bool(pending),
        "operation_logs": PipelineOperationLog.select().where(lookup).count(),
        "apply": args.apply,
    }
    if args.apply:
        # Exclusive creation preserves the original evidence on accidental reruns.
        fd = os.open(Path(args.backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"queue": args.queue, "group": group, "message": rows, "task": task.to_dict()}, out, ensure_ascii=False, default=str)
        if not PipelineOperationLog.select().where(lookup).exists():
            PipelineOperationLogService.record_pipeline_operation(task.doc_id, "", PipelineTaskType.STRUCTURE_GRAPH, task.id, doc.id)
        operation = PipelineOperationLog.select().where(lookup).get()
        if operation.progress != 1 or operation.operation_status != "3":
            raise RuntimeError("Operation log is not successful; refusing ACK")
        report["acked"] = redis.xack(args.queue, group, args.message_id)
        report["operation_logs"] = PipelineOperationLog.select().where(lookup).count()
    print(json.dumps(report, ensure_ascii=False))
    redis.close()


if __name__ == "__main__":
    main()
