"""Explicit, versioned export formats over immutable canonical samples."""

import copy
import hashlib
import io
import json
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from . import assets
from .schema import evidence_refs, query_text
from .source import FactoryError, canonical
from .store import evidence_map

ADAPTERS = [
    {"id": "canonical-v2", "tasks": ["embedding", "reranker", "llm"], "modalities": ["text", "image", "audio", "video", "structured"], "name": "Canonical 多模态 JSONL"},
    {"id": "sentence-transformers-triplet-v1", "tasks": ["embedding"], "modalities": ["text"], "name": "Sentence Transformers anchor / positive / negative"},
    {"id": "reranker-pointwise-v1", "tasks": ["reranker"], "modalities": ["text"], "name": "Reranker query / document / label"},
    {"id": "messages-v1", "tasks": ["llm"], "modalities": ["text", "image", "audio", "video", "structured"], "name": "Messages + 相对路径媒体"},
    {"id": "llama-factory-sharegpt-v1", "tasks": ["llm"], "modalities": ["text", "image", "audio", "video"], "name": "LLaMA-Factory ShareGPT 多模态"},
]


def build(db, dataset, version, adapter):
    spec = next((a for a in ADAPTERS if a["id"] == adapter), None)
    if not spec or dataset["task"] not in spec["tasks"]:
        raise FactoryError("适配器不支持当前任务")
    row = db.execute("SELECT members FROM version WHERE dataset=? AND id=?", (dataset["id"], version)).fetchone()
    if not row:
        raise FactoryError("版本不存在", 404)
    evidence = evidence_map(db, dataset["id"])
    files = {s + ".jsonl": [] for s in ("train", "validation", "test")}
    media = {}
    provenance = []

    def materialize(parts):
        result = copy.deepcopy(parts)
        for part in result:
            if part["type"] not in spec["modalities"]:
                raise FactoryError("适配器不支持 " + part["type"] + "，请选择 Canonical 格式")
            if part.get("asset_id"):
                item, data = assets.read(db, dataset["owner"], part["asset_id"])
                name = assets.archive_name(item)
                media[name] = data
                part["path"] = name
        return result

    for sid, rev in json.loads(row[0]):
        sample = json.loads(db.execute("SELECT body FROM revision WHERE dataset=? AND id=? AND rev=?", (dataset["id"], sid, rev)).fetchone()[0])
        refs = evidence_refs(sample)
        proof = {eid: dict(evidence[eid], parts=materialize(evidence[eid]["parts"])) for eid in refs}
        payload = sample["payload"]
        if sample["task"] != "llm":
            materialize(payload["query"])
        if adapter == "sentence-transformers-triplet-v1":
            rows = [{"anchor": query_text(sample), "positive": proof[p]["text"], "negative": proof[n["evidence_id"]]["text"]} for p in payload["positives"] for n in payload["negatives"]]
        elif adapter == "reranker-pointwise-v1":
            rows = [{"query": query_text(sample), "document": proof[c["evidence_id"]]["text"], "label": c["label"]} for c in payload["candidates"]]
        elif adapter == "llama-factory-sharegpt-v1":
            turns = payload["messages"]
            if payload["supervised_turns"] != [i for i, m in enumerate(turns) if m["role"] == "assistant"]:
                raise FactoryError("ShareGPT 适配器要求监督所有 assistant 轮次")
            exported = {"conversations": [], "images": [], "audios": [], "videos": []}
            expected = "user"
            for index, turn in enumerate(turns):
                if turn["role"] == "system" and index == 0:
                    pass
                elif turn["role"] != expected:
                    raise FactoryError("ShareGPT 导出要求 user/assistant 交替，system 仅在首轮")
                else:
                    expected = "assistant" if expected == "user" else "user"
                content = []
                for part in materialize(turn["content"]):
                    if part["type"] == "text":
                        if any(tag in part["text"] for tag in ("<image>", "<audio>", "<video>")):
                            raise FactoryError("文本中已有媒体占位符，请改用 ContentPart 资产引用")
                        content.append(part["text"])
                    else:
                        if part.get("region") or part.get("time_ms"):
                            raise FactoryError("需先物化裁剪区域或时间片段再导出 ShareGPT")
                        exported[part["type"] + "s"].append(part["path"])
                        content.append("<" + part["type"] + ">")
                exported["conversations"].append({"from": {"user": "human", "assistant": "gpt", "system": "system"}[turn["role"]], "value": "\n".join(content)})
            if expected != "user":
                raise FactoryError("ShareGPT 对话必须以 assistant 回答结束")
            rows = [exported]
        elif adapter == "messages-v1":
            rows = [{"messages": [dict(m, content=materialize(m["content"])) for m in payload["messages"]], "supervised_turns": payload["supervised_turns"], "evidence": proof}]
        else:
            if "query" in payload:
                payload["query"] = materialize(payload["query"])
            if "messages" in payload:
                payload["messages"] = [dict(m, content=materialize(m["content"])) for m in payload["messages"]]
            rows = [dict(sample, evidence=proof)]
        files[sample["split"] + ".jsonl"].extend(canonical(r) + "\n" for r in rows)
        provenance.append({"sample_id": str(sid), "revision": rev, "provenance": sample["provenance"], "evidence_ids": refs})
    # Include original/derived relationships, so consumers can reconstruct page and crop lineage offline.
    lineage = []
    for row in db.execute("SELECT * FROM asset_ref WHERE dataset=? AND role!='published_export' ORDER BY sha,doc,role", (dataset["id"],)):
        item, data = assets.read(db, row["owner"], row["sha"])
        name = assets.archive_name(item)
        media[name] = data
        lineage.append(
            {
                "asset_id": row["sha"],
                "path": name,
                "mime": item["mime"],
                "parent_asset_id": row["parent"] or None,
                "document_id": row["doc"],
                "role": row["role"],
                "locator": json.loads(row["locator"]),
            }
        )
    blobs = {name: "".join(lines).encode() for name, lines in files.items()}
    blobs["provenance.jsonl"] = "".join(canonical(p) + "\n" for p in provenance).encode()
    blobs.update(media)
    if adapter == "llama-factory-sharegpt-v1":
        blobs["dataset_info.json"] = canonical(
            {
                "factory_" + split: {"file_name": split + ".jsonl", "formatting": "sharegpt", "columns": {"messages": "conversations", "images": "images", "audios": "audios", "videos": "videos"}}
                for split in ("train", "validation", "test")
                if files[split + ".jsonl"]
            }
        ).encode()
    manifest = {
        "schema_version": 2,
        "adapter": adapter,
        "dataset": dataset["id"],
        "version": version,
        "task": dataset["task"],
        "snapshot_id": dataset["snapshot"],
        "config": json.loads(dataset["config"]),
        "assets": lineage,
        "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(blobs.items())},
        "split_rows": {name: len(rows) for name, rows in files.items()},
        "invocations": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "state": r["state"],
                "model_id": r["model"],
                "reserved_tokens": r["reserved"],
                "reported_model_name": json.loads(r["result"]).get("model_name") if r["result"] else None,
            }
            for r in db.execute("SELECT * FROM invocation WHERE dataset=? ORDER BY id", (dataset["id"],))
        ],
    }
    blobs["manifest.json"] = canonical(manifest).encode()
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, data in sorted(blobs.items()):
            archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
    return buffer.getvalue()
