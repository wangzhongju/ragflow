"""Data preparation HTTP domain; consumed by RAGFlow Web or an independent client."""

import json
from datetime import UTC, datetime
from uuid import UUID

from flask import Flask, Response, g, jsonify, request

from . import assets
from .adapters import ADAPTERS, build
from .embedding import normalize
from .jobs import produce, worker
from .quality import findings, require_valid
from .schema import Sample, evidence_refs, query_text, settings
from .source import FactoryError, Source, canonical, digest, identifier
from .store import current_samples, database, evidence_map, initialize

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 262144
prefix = "/api/v1/data-factory"
initialize()


@app.errorhandler(FactoryError)
def error(exc):
    return jsonify(error=str(exc)), exc.status


@app.before_request
def identity():
    if request.path.startswith(prefix + "/"):
        g.source = Source(request.headers.get("Authorization"))
        g.owner = g.source.get("/users/me")["id"]


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
def health():
    with database() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get(prefix + "/capabilities")
def capabilities():
    return {"enabled": True, "tasks": ["embedding", "reranker", "llm"], "adapters": ADAPTERS, "defaults": settings({}), "modalities": ["text", "image", "audio", "video", "structured"]}


def body():
    value = request.get_json()
    if not isinstance(value, dict):
        raise FactoryError("请输入 JSON 对象")
    return value


def dataset(ds, role=None):
    with database() as db:
        row = db.execute(
            """SELECT d.*,m.role FROM dataset d LEFT JOIN member m ON m.dataset=d.id AND m.user=?
                          WHERE d.id=? AND (d.owner=? OR m.user IS NOT NULL)""",
            (g.owner, ds, g.owner),
        ).fetchone()
    if not row:
        raise FactoryError("制作实例不存在", 404)
    if row["owner"] != g.owner:
        if role and role != row["role"]:
            raise FactoryError("没有此操作的权限", 403)
        if not any(t["tenant_id"] == row["owner"] and t["role"] in ("normal", "admin") for t in g.source.get("/tenants")):
            raise FactoryError("团队成员权限已撤销", 403)
    g.source.authorize(json.loads(row["sources"]))
    return row


@app.get(prefix + "/models")
def models():
    return jsonify(g.source.get("/models"))


@app.get(prefix + "/sources")
def sources():
    page = request.args.get("page", 1, type=int)
    if not 1 <= page <= 100000:
        raise FactoryError("页码无效")
    params = {"page": page, "page_size": 50, "keywords": request.args.get("keywords", "")[:120]}
    kb = request.args.get("kb")
    rows = g.source.get("/datasets/" + identifier(kb) + "/documents", run="DONE", **params)["docs"] if kb else g.source.get("/datasets", **params)
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@app.get(prefix + "/datasets")
def listing():
    with database() as db:
        rows = db.execute(
            """SELECT id,name,state,task FROM dataset WHERE owner=? OR id IN
                           (SELECT dataset FROM member WHERE user=?) ORDER BY created DESC""",
            (g.owner, g.owner),
        ).fetchall()
    result = []
    for row in rows:
        try:
            dataset(row["id"])
            result.append(dict(row))
        except FactoryError as exc:
            if exc.status not in (403, 404):
                raise
    return jsonify(result)


@app.post(prefix + "/datasets")
def create():
    data = body()
    try:
        ds = str(UUID(str(data.get("request_id"))))
    except ValueError:
        raise FactoryError("提交标识必须为 UUID") from None
    task = data.get("task", "embedding")
    if task not in ("embedding", "reranker", "llm"):
        raise FactoryError("任务类型无效")
    config = settings(data.get("config"))
    if task == "llm" and not config["model_id"]:
        raise FactoryError("LLM 制作需要选择生成模型")
    name = data.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise FactoryError("实例名称应为 1 至 120 字符")
    pairs = data.get("sources")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 16 or any(not isinstance(p, list) or len(p) != 2 for p in pairs):
        raise FactoryError("请选择 1 至 16 个来源文档")
    pairs = sorted([[identifier(k), identifier(d)] for k, d in pairs])
    if len({d for _, d in pairs}) != len(pairs):
        raise FactoryError("来源文档重复")
    g.source.authorize(pairs)
    if config["model_id"] and not any(m["model_id"] == config["model_id"] and "chat" in m["model_type"] for m in g.source.get("/models")):
        raise FactoryError("无权使用所选生成模型", 403)
    if config["rerank_id"] and not any(m["model_id"] == config["rerank_id"] and "rerank" in m["model_type"] for m in g.source.get("/models")):
        raise FactoryError("无权使用所选 Rerank 模型", 403)
    with database(True) as db:
        old = db.execute("SELECT * FROM dataset WHERE id=?", (ds,)).fetchone()
        if old:
            if (old["owner"], old["sources"], old["name"], old["task"], old["config"]) != (g.owner, canonical(pairs), name, task, canonical(config)):
                raise FactoryError("提交标识已用于其他配置", 409)
            return {"id": ds, "state": old["state"]}
        if db.execute("SELECT count(*) FROM dataset WHERE owner=? AND state IN ('queued','running')", (g.owner,)).fetchone()[0] >= 3:
            raise FactoryError("已有三个未完成的任务", 429)
        db.execute("INSERT INTO dataset(id,owner,name,sources,state,task,config) VALUES(?,?,?,?,'queued',?,?)", (ds, g.owner, name, canonical(pairs), task, canonical(config)))
    worker.submit(produce, ds, 0, g.source)
    return {"id": ds, "state": "queued"}, 202


@app.get(prefix + "/datasets/<ds>")
def detail(ds):
    row = dataset(ds)
    with database() as db:
        counts = dict(
            db.execute(
                """SELECT r.status,count(*) FROM revision r JOIN
             (SELECT id,MAX(rev) rev FROM revision WHERE dataset=? GROUP BY id) l ON r.id=l.id AND r.rev=l.rev
             WHERE r.dataset=? GROUP BY r.status""",
                (ds, ds),
            )
        )
        used = db.execute("SELECT count(*),coalesce(sum(reserved),0) FROM invocation WHERE dataset=?", (ds,)).fetchone()
        media = [
            dict(a)
            for a in db.execute(
                "SELECT r.*,a.mime,a.name,a.size,a.metadata FROM asset_ref r JOIN asset a ON a.owner=r.owner AND a.sha=r.sha WHERE dataset=? AND role!='published_export' ORDER BY doc,role", (ds,)
            )
        ]
        return {
            "id": ds,
            "name": row["name"],
            "task": row["task"],
            "state": row["state"],
            "error": row["error"],
            "config": json.loads(row["config"]),
            "sources": json.loads(row["sources"]),
            "snapshot": row["snapshot"],
            "counts": counts,
            "role": row["role"] if row["owner"] != g.owner else "owner",
            "captured": db.execute("SELECT count(*) FROM capture WHERE dataset=?", (ds,)).fetchone()[0],
            "calls": used[0],
            "reserved_tokens": used[1],
            "assets": media,
            "versions": [r[0] for r in db.execute("SELECT id FROM version WHERE dataset=? ORDER BY rowid DESC", (ds,))],
        }


@app.post(prefix + "/datasets/<ds>/jobs/<action>")
def control(ds, action):
    row = dataset(ds, "owner")
    with database(True) as db:
        if action == "cancel":
            db.execute("UPDATE dataset SET state='cancelled' WHERE id=? AND state IN ('queued','running')", (ds,))
            return {"id": ds}
        if action != "retry":
            raise FactoryError("任务操作无效", 404)
        if not db.execute("UPDATE dataset SET state='queued',attempt=attempt+1,error='' WHERE id=? AND attempt=? AND state IN ('cancelled','failed','interrupted')", (ds, row["attempt"])).rowcount:
            raise FactoryError("此状态不能继续", 409)
    worker.submit(produce, ds, row["attempt"] + 1, g.source)
    return {"id": ds}, 202


@app.get(prefix + "/datasets/<ds>/samples")
def samples(ds):
    dataset(ds)
    page = request.args.get("page", 1, type=int)
    if page < 1:
        raise FactoryError("页码无效")
    with database() as db:
        evidence = evidence_map(db, ds)
        result = []
        for row in current_samples(db, ds, 20, (page - 1) * 20):
            sample = json.loads(row["body"])
            result.append(
                {
                    "id": row["id"],
                    "revision": row["rev"],
                    "status": row["status"],
                    "sample": sample,
                    "evidence": {eid: evidence[eid] for eid in evidence_refs(sample)},
                    "quality": findings(sample, evidence),
                }
            )
    return jsonify(result)


@app.get(prefix + "/datasets/<ds>/evidence")
def evidence(ds):
    dataset(ds)
    page = request.args.get("page", 1, type=int)
    with database() as db:
        rows = db.execute("SELECT body FROM evidence WHERE dataset=? ORDER BY id LIMIT 50 OFFSET ?", (ds, max(0, page - 1) * 50))
        return jsonify([json.loads(r[0]) for r in rows])


@app.post(prefix + "/datasets/<ds>/samples/<int:sid>/review")
def review(ds, sid):
    dataset(ds, "reviewer")
    data = body()
    status = data.get("status")
    if status not in ("draft", "approved", "rejected"):
        raise FactoryError("审核状态无效")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 2000 or (status == "rejected" and not reason.strip()):
        raise FactoryError("请输入有效审核备注，驳回时必填")
    with database(True) as db:
        old = db.execute("SELECT * FROM revision WHERE dataset=? AND id=? ORDER BY rev DESC LIMIT 1", (ds, sid)).fetchone()
        if not old or old["rev"] != data.get("revision"):
            raise FactoryError("修订已改变，请刷新", 409)
        sample = json.loads(old["body"])
        sample["payload"] = data.get("payload", sample["payload"])
        try:
            Sample.model_validate(sample)
            refs = evidence_refs(sample)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise FactoryError("任务 payload 结构无效") from None
        evidence = evidence_map(db, ds)
        if any(eid not in evidence or evidence[eid]["split"] != sample["split"] for eid in refs):
            raise FactoryError("证据不存在或跨越分区")
        # All user-supplied media parts must belong to this captured dataset.
        allowed = {r[0] for r in db.execute("SELECT sha FROM asset_ref WHERE dataset=?", (ds,))}

        def verify_media(value):
            if isinstance(value, dict):
                if value.get("asset_id") and value["asset_id"] not in allowed:
                    raise FactoryError("媒体资产不属于当前来源")
                for child in value.values():
                    verify_media(child)
            elif isinstance(value, list):
                for child in value:
                    verify_media(child)

        verify_media(sample["payload"])
        sample["evidence_ids"] = refs
        sample["revision"] = old["rev"] + 1
        primary_ids = sample["payload"].get("positives") or refs
        primary = primary_ids[0] if primary_ids else None
        if primary:
            sample["group_id"] = evidence[primary]["group_id"]
        sample["provenance"]["review"] = {"actor": g.owner, "status": status, "reason": reason, "reviewed_at": datetime.now(UTC).isoformat()}
        if sample["payload"] != json.loads(old["body"])["payload"]:
            sample["provenance"]["manually_edited"] = True
        if status == "approved":
            require_valid(sample, evidence)
        db.execute("INSERT INTO revision(dataset,id,rev,body,status,actor,reason) VALUES(?,?,?,?,?,?,?)", (ds, sid, sample["revision"], canonical(sample), status, g.owner, reason))
    return {"revision": sample["revision"]}


@app.get(prefix + "/datasets/<ds>/quality")
def quality(ds):
    dataset(ds)
    with database() as db:
        evidence = evidence_map(db, ds)
        rows = []
        for row in current_samples(db, ds):
            sample = json.loads(row["body"])
            rows.append(
                {"id": row["id"], "revision": row["rev"], "status": row["status"], "split": sample["split"], "issues": findings(sample, evidence), "warnings": sample["provenance"].get("warnings", [])}
            )
        return {"samples": rows, "total": len(rows), "blocked": sum(bool(r["issues"]) for r in rows), "approved": sum(r["status"] == "approved" for r in rows)}


@app.post(prefix + "/datasets/<ds>/versions")
def freeze(ds):
    row = dataset(ds, "publisher")
    if row["state"] != "ready":
        raise FactoryError("生成尚未完成", 409)
    with database(True) as db:
        evidence = evidence_map(db, ds)
        seen = set()
        members = []
        for revision in current_samples(db, ds):
            if revision["status"] != "approved":
                continue
            sample = json.loads(revision["body"])
            require_valid(sample, evidence)
            query = normalize(query_text(sample)) or digest(canonical(sample["payload"]["query"]))
            if query in seen:
                raise FactoryError("已批准样本存在重复问题，请合并")
            seen.add(query)
            members.append([revision["id"], revision["rev"]])
        if not members:
            raise FactoryError("没有已批准样本")
        version = digest(canonical([row["snapshot"], members, row["config"]]))
        db.execute("INSERT OR IGNORE INTO version(dataset,id,members) VALUES(?,?,?)", (ds, version, canonical(members)))
    return {"version": version, "count": len(members)}


@app.get(prefix + "/datasets/<ds>/assets/<sha>")
def asset(ds, sha):
    row = dataset(ds)
    with database() as db:
        if not db.execute("SELECT 1 FROM asset_ref WHERE dataset=? AND sha=?", (ds, sha)).fetchone():
            raise FactoryError("资产不存在", 404)
        item, data = assets.read(db, row["owner"], sha)
    return Response(data, mimetype=item["mime"], headers={"Content-Disposition": "attachment; filename=" + sha})


@app.get(prefix + "/datasets/<ds>/versions/<version>/download")
def download(ds, version):
    row = dataset(ds, "publisher")
    adapter = request.args.get("adapter", "canonical-v2")
    with database() as db:
        archive = db.execute("SELECT sha,locator FROM asset_ref WHERE dataset=? AND role='published_export'", (ds,)).fetchall()
        original = next((a for a in archive if json.loads(a["locator"]).get("version") == version), None)
        if original:
            if adapter != "canonical-v2":
                raise FactoryError("历史冻结版本仅提供原始发布包，请用新实例制作新版格式")
            _, data = assets.read(db, row["owner"], original["sha"])
            return Response(data, mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="published-' + version[:12] + '.zip"'})
        cached = db.execute("SELECT sha FROM export_file WHERE dataset=? AND version=? AND adapter=?", (ds, version, adapter)).fetchone()
        if cached:
            _, data = assets.read(db, row["owner"], cached[0])
        else:
            data = build(db, row, version, adapter)
    with database(True) as db:
        if not cached:
            sha = assets.register(db, row["owner"], data, "application/zip", version + ".zip")
            db.execute("INSERT OR IGNORE INTO export_file VALUES(?,?,?,?,?)", (ds, version, adapter, row["owner"], sha))
        db.execute("INSERT INTO audit(dataset,actor,version) VALUES(?,?,?)", (ds, g.owner, version))
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{row["task"]}-{version[:12]}.zip"'})


@app.post(prefix + "/datasets/<ds>/members")
def membership(ds):
    dataset(ds, "owner")
    data = body()
    user = identifier(data.get("user"))
    role = data.get("role")
    if role not in ("reviewer", "publisher", "remove"):
        raise FactoryError("角色无效")
    if role != "remove" and not any(m["user_id"] == user and m["role"] in ("normal", "admin") for m in g.source.get("/tenants/" + g.owner + "/users")):
        raise FactoryError("用户尚未加入本团队", 403)
    with database(True) as db:
        db.execute("DELETE FROM member WHERE dataset=? AND user=?", (ds, user))
        if role != "remove":
            db.execute("INSERT INTO member VALUES(?,?,?)", (ds, user, role))
    return {"role": role}


@app.delete(prefix + "/datasets/<ds>")
def remove(ds):
    with database(True) as db:
        if not db.execute("SELECT 1 FROM dataset WHERE id=? AND owner=?", (ds, g.owner)).fetchone():
            raise FactoryError("实例不存在", 404)
        for table in ("invocation", "audit", "export_file", "version", "revision", "asset_ref", "capture", "evidence", "member"):
            db.execute(f"DELETE FROM {table} WHERE dataset=?", (ds,))
        db.execute("DELETE FROM dataset WHERE id=?", (ds,))
        assets.collect_unreferenced(db, g.owner)
    return {"deleted": ds}
