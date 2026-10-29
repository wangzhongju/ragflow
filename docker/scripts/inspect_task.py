"""Read-only task inspection inside the application container; see docs/troubleshooting.md."""

import argparse
import json
import os
import time
from datetime import datetime

import pymysql
import valkey


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc-id", help="Document ID; omit to list the latest 10 documents")
    args = parser.parse_args()
    env = os.environ
    report = {"collected_at": datetime.now().astimezone().isoformat()}
    connection = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DBNAME"],
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=20,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION READ ONLY")
            query = (
                "SELECT id,kb_id,name,run,progress,chunk_num,pipeline_id,"
                "process_begin_at,process_duration,update_date,"
                "RIGHT(progress_msg,4000) AS recent_log FROM document "
            )
            if args.doc_id:
                cursor.execute(query + "WHERE id=%s", (args.doc_id,))
            else:
                cursor.execute(query + "ORDER BY create_time DESC LIMIT 10")
            documents = cursor.fetchall()
            report["documents"] = documents
            if args.doc_id and not documents:
                raise SystemExit("Document not found; verify the ID and deployment.")
            if args.doc_id:
                document = documents[0]
                cursor.execute(
                    "SELECT id,doc_id,task_type,priority,progress,retry_count,begin_at,"
                    "update_date,RIGHT(progress_msg,4000) AS recent_log "
                    "FROM task WHERE doc_id=%s ORDER BY create_time DESC",
                    (args.doc_id,),
                )
                report["tasks"] = cursor.fetchall()
                cursor.execute(
                    "SELECT id,name,graphrag_task_id,structure_graph_task_id,structure_task_id "
                    "FROM knowledgebase WHERE id=%s",
                    (document["kb_id"],),
                )
                report["knowledgebase"] = cursor.fetchone()
                report["dataset_graph_tasks"] = []
                for field in ("graphrag_task_id", "structure_graph_task_id", "structure_task_id"):
                    graph_id = (report["knowledgebase"] or {}).get(field)
                    if not graph_id:
                        continue
                    cursor.execute(
                        "SELECT id,task_type,progress,update_date,"
                        "RIGHT(progress_msg,2000) AS recent_log FROM task WHERE id=%s",
                        (graph_id,),
                    )
                    report["dataset_graph_tasks"].append({"reference_field": field, "task": cursor.fetchone()})
                if document["pipeline_id"]:
                    cursor.execute("SELECT dsl FROM user_canvas WHERE id=%s", (document["pipeline_id"],))
                    row = cursor.fetchone()
                    if row:
                        dsl = json.loads(row["dsl"]) if isinstance(row["dsl"], str) else row["dsl"]
                        components = []
                        for component_id, component in dsl.get("components", {}).items():
                            obj = component.get("obj", {})
                            item = {"id": component_id, "type": obj.get("component_name")}
                            if item["type"] == "Parser":
                                pdf = obj.get("params", {}).get("setups", {}).get("pdf", {})
                                item["pdf"] = {
                                    key: pdf.get(key)
                                    for key in ("parse_method", "output_format", "flatten_media_to_text")
                                }
                            components.append(item)
                        report["pipeline"] = {"component_count": len(components), "components": components}
    finally:
        connection.rollback()
        connection.close()

    if args.doc_id:
        redis = valkey.Valkey(
            host=env["REDIS_HOST"],
            port=int(env.get("REDIS_PORT", "6379")),
            password=env["REDIS_PASSWORD"],
            db=1,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
        )
        try:
            stats = redis.info("stats")
            report["redis"] = {key: stats.get(key) for key in ("evicted_keys", "expired_keys")}
            report["pipeline_log_ttl"] = []
            for task in report["tasks"]:
                if task["task_type"] != "dataflow" or not document["pipeline_id"]:
                    continue
                key = f"{document['pipeline_id']}-{task['id']}-logs"
                report["pipeline_log_ttl"].append({"task_id": task["id"], "key": key, "ttl": redis.ttl(key)})
            report["workers"] = []
            for name in sorted(redis.smembers("TASKEXE")):
                latest = redis.zrevrange(name, 0, 0, withscores=True)
                if not latest:
                    report["workers"].append({"name": name, "heartbeat": "missing"})
                    continue
                heartbeat = json.loads(latest[0][0])
                current = heartbeat.get("current") or {}
                report["workers"].append(
                    {
                        "name": name,
                        "age_seconds": round(time.time() - latest[0][1], 1),
                        "pending": heartbeat.get("pending"),
                        "lag": heartbeat.get("lag"),
                        "done": heartbeat.get("done"),
                        "failed": heartbeat.get("failed"),
                        "current_task_ids": list(current) if isinstance(current, dict) else [],
                    }
                )
            report["queues"] = []
            known_tasks = {task["id"]: task["progress"] for task in report["tasks"]}
            for entry in report["dataset_graph_tasks"]:
                if entry["task"]:
                    known_tasks[entry["task"]["id"]] = entry["task"]["progress"]
            for priority in (1, 0):
                key = f"te.{priority}.common"
                if redis.type(key) != "stream":
                    continue
                groups = redis.xinfo_groups(key)
                queue = {"name": key, "groups": groups, "pending_sample": []}
                for group in groups:
                    if group["name"] != "rag_flow_svr_task_broker":
                        continue
                    for pending in redis.xpending_range(key, group["name"], "-", "+", 10):
                        rows = redis.xrange(key, pending["message_id"], pending["message_id"])
                        body = json.loads(rows[0][1]["message"]) if rows else {}
                        task_id = body.get("id")
                        queue["pending_sample"].append(
                            {
                                **pending,
                                "task_id": task_id,
                                "known_task_progress": known_tasks.get(task_id),
                            }
                        )
                report["queues"].append(queue)
        except valkey.exceptions.RedisError as error:
            report["redis_error"] = f"{type(error).__name__}: {error}"
        finally:
            redis.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
