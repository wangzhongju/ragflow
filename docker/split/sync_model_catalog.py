"""Tongyi metadata synchronization on the Linux app host: plan/apply/verify/rollback.

HTTP and database operations run inside the app container. No inference requests,
billing changes, workflow replacements, or dataset rebuilds are performed.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PROVIDER = "Tongyi-Qianwen"
TZ = ZoneInfo("Asia/Shanghai")
BITS = {"chat": 1, "embedding": 2, "speech2text": 4, "image2text": 8, "rerank": 16, "tts": 32}
ROOT = Path(__file__).resolve().parent.parent.parent


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data, exclusive=False):
    path = Path(path)
    if exclusive:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save(path, value, exclusive=False):
    _write(path, (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode(), exclusive)


def _offline(model):
    value = model.get("inference_offline_info")
    if not value:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("offline_time"), str):
        raise TypeError(f"Unrecognized offline metadata: {model['model']}")
    result = datetime.fromisoformat(value["offline_time"].replace("Z", "+00:00"))  # noqa: FURB162 -- the deployment host runs Python 3.10.
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result


def _fetch_pages(session, endpoint, site):
    models, pages, total = [], [], None
    for page in range(1, 101):
        response = session.get(endpoint, params={"page_no": page, "page_size": 100, "service_site": site, "supports": "inference"}, timeout=40, allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        output = body.get("output", {})
        if body.get("success") is not True or not isinstance(output.get("total"), int) or output.get("page_no") != page:
            raise ValueError("Official list returned an unexpected schema or page")
        if total is None:
            total = output["total"]
        if total <= 0 or total != output["total"] or not isinstance(output.get("models"), list) or not output["models"]:
            raise ValueError("Empty, incomplete, or changing official catalog")
        pages.append(body)
        models.extend(output["models"])
        names = [m.get("model") for m in models]
        if any(not isinstance(n, str) or not n or len(n) > 128 for n in names) or len(set(names)) != len(names) or len(models) > total:
            raise ValueError("Duplicate or invalid models in paginated catalog")
        if len(models) == total:
            return {"endpoint": endpoint, "service_site": site, "total": total, "pages": pages, "models": models}
    raise ValueError("Pagination limit exceeded")


def _normalize(model, policy, previous):
    """Match capabilities to contracts implemented by the current Tongyi adapters."""
    name = model["model"]
    caps = set(model["capabilities"])
    inputs = set(model["inference_metadata"]["request_modality"])
    outputs = set(model["inference_metadata"]["response_modality"])
    if caps & {"TG", "VU"} and "Text" in outputs:
        if name.startswith(("qwen-mt", "qwen-deep-research", "decision-model")):
            return None, "Requires specialized request options outside the chat adapter"
        types = ["chat"] + (["image2text"] if "VU" in caps and "Image" in inputs else [])
    elif "TR" in caps:
        if re.fullmatch(r"(?:qwen[\d.]+-text-embedding(?:-flash)?|text-embedding-v\d+)", name):
            types = ["embedding"]
        elif name in {"qwen3.7-text-rerank", "qwen3-rerank", "gte-rerank-v2"}:
            types = ["rerank"]
        else:
            return None, "Vector/rerank API needs adapter review (not chat)"
    elif "ASR" in caps and (name == "qwen3-asr-flash" or re.fullmatch(r"fun-asr-flash(?:-\d{4}-\d{2}-\d{2})?", name)):
        types = ["speech2text"]
    elif "TTS" in caps and name.startswith("sambert-"):
        types = ["tts"]
    else:
        return None, "No matching Tongyi adapter for these capabilities/API"
    info = model["model_info"]
    limit = info.get("context_window") or info.get("max_input_tokens") or policy["token_limits"].get(name)
    if not limit and types in (["speech2text"], ["tts"]):
        limit = 0  # These APIs limit duration/characters instead of context tokens.
    if limit is None:
        return None, "Missing token limit; add a sourced token_limits rule"
    if not isinstance(limit, int) or limit < 0:
        raise ValueError(f"Invalid token limit: {name}")
    result = {"llm_name": name, "model_type": types, "max_tokens": limit, "is_tools": "function-calling" in model["features"], "features": ["thinking"] if "Reasoning" in caps else []}
    for field in ("rank", "tags"):
        if field in previous:
            result[field] = previous[field]
    return result, None


def _build_catalog(catalog, official, policy, now):
    result = copy.deepcopy(catalog)
    factory = next(f for f in result["factory_llm_infos"] if f["name"] == PROVIDER)
    old = {m["llm_name"]: m for m in factory["llm"]}
    if len(old) != len(factory["llm"]):
        raise ValueError("Duplicate existing catalog entries")
    retired = {n for g in policy["retirements"] if datetime.fromisoformat(g["effective_at"]).replace(tzinfo=TZ) <= now for n in g["models"]}
    new, excluded, scheduled = {}, {}, {}
    for model in official["models"]:
        name, deadline = model["model"], _offline(model)
        if deadline and deadline <= now:
            retired.add(name)
        elif deadline:
            scheduled[name] = deadline.isoformat()
        if name in retired:
            excluded[name] = "Retirement date has arrived"
            continue
        normalized, reason = _normalize(model, policy, old.get(name, {}))
        if normalized:
            new[name] = normalized
        else:
            excluded[name] = reason
    retained = {}
    for name, model in old.items():
        if name not in new and name not in retired:
            new[name] = model
            retained[name] = excluded.get(name, "Absent from regional snapshot; retirement unconfirmed")
    factory["llm"] = sorted(new.values(), key=lambda m: m["llm_name"])
    report = {
        "official_count": len(official["models"]),
        "catalog_before": len(old),
        "catalog_after": len(new),
        "add": sorted(new.keys() - old.keys()),
        "update": sorted(n for n in new.keys() & old.keys() if new[n] != old[n]),
        "remove": sorted(old.keys() - new.keys()),
        "retained_for_review": retained,
        "excluded": excluded,
        "scheduled_retirements": scheduled,
        "effective_retirements": sorted(retired),
    }
    return result, report


def _plan_rows(rows, desired, retired, instance, now, preserve_names=()):
    by_name = {r["model_name"]: r for r in rows}
    if len(by_name) != len(rows):
        raise ValueError("Duplicate instance model names")
    result = {n: copy.deepcopy(r) for n, r in by_name.items() if n not in retired}
    stamp, millis = now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp() * 1000)
    for model in desired:
        name = model["llm_name"]
        existing = result.get(name)
        if existing and name in preserve_names:
            continue
        extra = json.loads(existing["extra"] or "{}") if existing else {"verify": "unknown"}
        extra.update(max_tokens=model.get("max_tokens", 8192), is_tools=model.get("is_tools", False), thinking="thinking" in model.get("features", []))
        types = model["model_type"] if isinstance(model["model_type"], list) else [model["model_type"]]
        bits = sum(BITS[t] for t in set(types))
        if existing:
            if existing["model_type"] == bits and json.loads(existing["extra"] or "{}") == extra:
                continue
            existing.update(model_type=bits, extra=_json(extra), update_time=millis, update_date=stamp)
        else:
            result[name] = {
                "id": uuid.uuid4().hex,
                "model_name": name,
                "provider_id": instance["provider_id"],
                "instance_id": instance["id"],
                "model_type": bits,
                "status": "active",
                "extra": _json(extra),
                "create_time": millis,
                "create_date": stamp,
                "update_time": millis,
                "update_date": stamp,
            }
    return sorted(result.values(), key=lambda r: r["id"])


def _db():
    import pymysql

    e = os.environ
    return pymysql.connect(
        host=e["MYSQL_HOST"],
        port=int(e["MYSQL_PORT"]),
        user=e["MYSQL_USER"],
        password=e["MYSQL_PASSWORD"],
        database=e["MYSQL_DBNAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=40,
        write_timeout=40,
    )


def _instance(q, instance_id):
    q.execute(
        "SELECT i.id,i.instance_name,i.provider_id,i.api_key,i.extra,p.provider_name,p.tenant_id FROM tenant_model_instance i JOIN tenant_model_provider p ON p.id=i.provider_id WHERE i.id=%s",
        (instance_id,),
    )
    instance = q.fetchone()
    if not instance or instance["provider_name"] != PROVIDER:
        raise ValueError("Instance does not belong to Tongyi-Qianwen")
    return instance


def _rows(q, instance, lock=False):
    q.execute("SELECT * FROM tenant_model WHERE instance_id=%s AND provider_id=%s ORDER BY id" + (" FOR UPDATE" if lock else ""), (instance["id"], instance["provider_id"]))
    return json.loads(_json(q.fetchall()))


def _worker(action, payload):
    with _db() as connection, connection.cursor() as q:
        instance = _instance(q, payload["instance_id"])
        if action == "snapshot":
            import requests

            key = instance.pop("api_key")
            try:
                key = json.loads(key)["api_key"]
            except (ValueError, TypeError):
                pass
            parsed = urlsplit(json.loads(instance.pop("extra"))["base_url"])
            if parsed.scheme != "https" or parsed.hostname != "dashscope.aliyuncs.com" or parsed.port not in (None, 443) or parsed.username:
                raise ValueError("This policy targets Beijing DashScope; another endpoint requires a reviewed regional policy")
            rows = _rows(q, instance)
            q.execute("SELECT id,title,dsl FROM user_canvas")
            canvases = q.fetchall()
            with requests.Session() as session:
                session.headers["Authorization"] = "Bearer " + key
                official = _fetch_pages(session, "https://dashscope.aliyuncs.com/api/v1/models", payload["service_site"])
            return {"instance": instance, "rows": rows, "canvases": canvases, "official": official}
        if action == "idle":
            q.execute("SELECT COUNT(*) AS n FROM document WHERE run='1'")
            if q.fetchone()["n"]:
                raise ValueError("Documents are running; retry after ingestion finishes")
            import valkey

            e = os.environ
            with valkey.Valkey(host=e["REDIS_HOST"], port=int(e.get("REDIS_PORT", 6379)), password=e["REDIS_PASSWORD"], db=1, decode_responses=True) as redis:
                for key in ("te.0.common", "te.1.common"):
                    if redis.type(key) == "stream" and any(g["pending"] or g.get("lag") for g in redis.xinfo_groups(key)):
                        raise ValueError("Task queue is not idle; retry after it drains")
            return {"idle": True}
        if action == "read":
            return {"rows": _rows(q, instance)}
        if action != "replace":
            raise ValueError("Unknown worker operation")
        connection.begin()
        current = _rows(q, instance, lock=True)
        if current != payload["expected"]:
            raise ValueError("Database changed since planning; create a fresh plan")
        target = payload["target"]
        allowed = {"id", "model_name", "provider_id", "instance_id", "model_type", "status", "extra", "create_time", "create_date", "update_time", "update_date"}
        before, after = {r["id"]: r for r in current}, {r["id"]: r for r in target}
        if len(after) != len(target):
            raise ValueError("Duplicate target IDs")
        for row in target:
            if set(row) != allowed or row["instance_id"] != instance["id"] or row["provider_id"] != instance["provider_id"] or len(row["extra"]) > 1024:
                raise ValueError("Invalid target row or instance scope")
        for model_id in before.keys() - after.keys():
            q.execute("DELETE FROM tenant_model WHERE id=%s AND instance_id=%s", (model_id, instance["id"]))
        for model_id, row in after.items():
            if before.get(model_id) == row:
                continue
            columns = list(row)
            if model_id in before:
                columns.remove("id")
                q.execute("UPDATE tenant_model SET " + ",".join(f"`{k}`=%s" for k in columns) + " WHERE id=%s AND instance_id=%s", [row[k] for k in columns] + [model_id, instance["id"]])
            else:
                q.execute("INSERT INTO tenant_model (" + ",".join(f"`{k}`" for k in columns) + ") VALUES (" + ",".join(["%s"] * len(columns)) + ")", [row[k] for k in columns])
        connection.commit()
        return {"count": len(target)}


def _call(container, action, payload):
    script = "/tmp/ragflow-tongyi-catalog-sync.py"
    subprocess.run(["docker", "cp", str(Path(__file__).resolve()), f"{container}:{script}"], check=True, stdout=subprocess.DEVNULL)
    process = subprocess.run(["docker", "exec", "-i", container, "python", script, "_worker", action], input=_json(payload), capture_output=True, text=True, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Catalog worker failed")
    return json.loads(process.stdout)


def _reload(container):
    subprocess.run(["bash", str(ROOT / "docker/split/ops.sh"), "app", "up", "-d", "--force-recreate", "--pull", "never"], check=True)
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        state = subprocess.check_output(["docker", "inspect", "--format", "{{.State.Health.Status}}", container], text=True).strip()
        if state == "healthy":
            return
        if state == "unhealthy":
            raise RuntimeError("Application unhealthy; inspect logs or roll back")
        time.sleep(5)
    raise RuntimeError("Application health timeout; plan and backup retained")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_worker":
        print(_json(_worker(sys.argv[2], json.load(sys.stdin))))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--instance-id")
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    container = "ragflow-app-ragflow-1"
    work = args.work_dir.resolve()
    catalog_path = ROOT / "conf/llm_factories.json"
    policy_path = ROOT / "docker/split/tongyi-sync-policy.json"
    if args.action == "plan":
        if not args.instance_id:
            parser.error("plan requires --instance-id")
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        policy_bytes = policy_path.read_bytes()
        policy = json.loads(policy_bytes)
        if policy["provider"] != PROVIDER or policy["service_site"] != "asia-pacific-china":
            raise ValueError("Wrong provider or regional policy")
        before = catalog_path.read_bytes()
        state = _call(container, "snapshot", {"instance_id": args.instance_id, "service_site": policy["service_site"]})
        now = datetime.now(TZ)
        after, report = _build_catalog(json.loads(before), state["official"], policy, now)
        factory = next(f for f in after["factory_llm_infos"] if f["name"] == PROVIDER)
        rows = _plan_rows(state["rows"], factory["llm"], report["effective_retirements"], state["instance"], now, report["retained_for_review"])
        original_text = before.decode("utf-8")
        anchor = original_text.index('"name": "Tongyi-Qianwen"')
        start = original_text.rfind("{", 0, anchor)
        _, length = json.JSONDecoder().raw_decode(original_text[start:])
        block = json.dumps(factory, ensure_ascii=False, indent=4).replace("\n", "\n        ")
        after_bytes = (original_text[:start] + block + original_text[start + length :]).encode()
        removed_ids = {r["id"] for r in state["rows"]} - {r["id"] for r in rows}
        report["workflow_references_to_removed"] = [
            {"id": c["id"], "title": c["title"], "model_ids": sorted(i for i in removed_ids if i in (c["dsl"] or ""))} for c in state["canvases"] if any(i in (c["dsl"] or "") for i in removed_ids)
        ]
        report.update(db_before=len(state["rows"]), db_after=len(rows), db_changed=state["rows"] != rows)
        plan = {
            "created_at": now.isoformat(),
            "instance": state["instance"],
            "before_sha256": _sha(before),
            "after_sha256": _sha(after_bytes),
            "policy_sha256": _sha(policy_bytes),
            "before_rows": state["rows"],
            "after_rows": rows,
            "report": report,
        }
        _write(work / "catalog.before.json", before, True)
        _write(work / "catalog.after.json", after_bytes, True)
        _save(work / "official.json", state["official"], True)
        _save(work / "plan.json", plan, True)
        _save(work / "report.json", report, True)
        print(
            _json({"work_dir": str(work), **{k: report[k] for k in ("official_count", "catalog_before", "catalog_after", "add", "update", "remove", "retained_for_review", "db_before", "db_after")}})
        )
        return
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    before, after = (work / "catalog.before.json").read_bytes(), (work / "catalog.after.json").read_bytes()
    if _sha(before) != plan["before_sha256"] or _sha(after) != plan["after_sha256"]:
        raise ValueError("Plan catalog files changed")
    payload = {"instance_id": plan["instance"]["id"]}
    if args.action == "verify":
        operation_path = work / "operation.json"
        operation = json.loads(operation_path.read_text(encoding="utf-8")) if operation_path.exists() else {}
        rolled_back = operation.get("action") == "rollback" and operation.get("phase") == "complete"
        expected_rows = plan["before_rows"] if rolled_back else plan["after_rows"]
        expected_file = before if rolled_back else after
        current = _call(container, "read", payload)["rows"]
        mounted = subprocess.check_output(["docker", "exec", container, "cat", "/ragflow/conf/llm_factories.json"])
        if current != expected_rows or catalog_path.read_bytes() != expected_file or mounted != expected_file:
            raise ValueError("Database, host catalog, or mounted catalog differs from plan")
        health = subprocess.check_output(["docker", "inspect", "--format", "{{.State.Health.Status}}", container], text=True).strip()
        if health != "healthy":
            raise ValueError(f"Application health is {health}")
        print(_json({"verified": True, "state": "before" if rolled_back else "after", "registered_count": len(current), "catalog_sha256": _sha(expected_file)}))
        return
    _call(container, "idle", payload)
    current_file = catalog_path.read_bytes()
    if args.action == "apply":
        now = datetime.now(TZ)
        if now - datetime.fromisoformat(plan["created_at"]) > timedelta(hours=24) or _sha(policy_path.read_bytes()) != plan["policy_sha256"]:
            raise ValueError("Plan expired or policy changed; generate a fresh plan")
        if any(datetime.fromisoformat(t) <= now for t in plan["report"]["scheduled_retirements"].values()):
            raise ValueError("Retirement deadline crossed; generate a fresh plan")
        if current_file != before:
            raise ValueError("Host catalog changed after planning")
        expected, target, new_file = plan["before_rows"], plan["after_rows"], after
    else:
        if current_file not in (before, after):
            raise ValueError("Catalog changed after this operation; refusing to overwrite it")
        current = _call(container, "read", payload)["rows"]
        if current not in (plan["before_rows"], plan["after_rows"]):
            raise ValueError("Model rows changed after this operation; refusing rollback")
        expected, target, new_file = current, plan["before_rows"], before
    _save(work / "operation.json", {"action": args.action, "phase": "before_database"})
    _call(container, "replace", {**payload, "expected": expected, "target": target})
    _save(work / "operation.json", {"action": args.action, "phase": "database_complete"})
    if current_file != new_file:
        _write(catalog_path, new_file)
    _save(work / "operation.json", {"action": args.action, "phase": "catalog_complete"})
    if args.action == "rollback" or current_file != new_file or expected != target:
        _reload(container)
    _save(work / "operation.json", {"action": args.action, "phase": "complete"})
    print(_json({"action": args.action, "registered_count": len(target), "catalog_sha256": _sha(new_file)}))


if __name__ == "__main__":
    main()
