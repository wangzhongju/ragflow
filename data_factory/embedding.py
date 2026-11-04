"""Evidence normalization and document-family partitioning shared by all tasks."""

import re
import unicodedata
from collections import defaultdict

from .source import FactoryError, digest


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def prepare(documents, config, check):
    parents = {d["doc"]: d["doc"] for d in documents}

    def root(doc):
        while parents[doc] != doc:
            parents[doc] = parents[parents[doc]]
            doc = parents[doc]
        return doc

    def merge(left, right):
        left, right = sorted((root(left), root(right)))
        parents[right] = left

    families = {}
    signatures = {}
    anchors = defaultdict(set)
    evidence = {}
    exact = {}
    for document in documents:
        doc = document["doc"]
        name = document["name"]
        keys = {("name", re.sub(r"(?:[-_ ](?:v|rev)?\d+(?:\.\d+)*)?(\.[^.]+)$", "", normalize(name)))}
        for chunk in document["chunks"]:
            check()
            content = (chunk["content"] or "").strip()
            parts = []
            if content:
                parts.append(dict({"type": "text", "text": content}, **({"asset_id": chunk["text_asset_id"]} if chunk.get("text_asset_id") else {})))
            if chunk.get("asset_sha256"):
                parts.append({"type": "image", "asset_id": chunk["asset_sha256"], "page": chunk["positions"][0][0] if chunk.get("positions") else None})
            if document.get("media_type") in ("audio", "video"):
                parts.append({"type": document["media_type"], "asset_id": document["original_asset"]})
            if chunk.get("doc_type_kwd") == "table" or "<table" in content.lower() or re.search(r"\|[^\n]+\|\s*\n\s*\|?\s*:?-{3}", content):
                parts.append({"type": "structured", "value": {"format": "table_text", "content": content}})
            if not parts:
                continue
            parts = [part for part in parts if part["type"] in config["modalities"]]
            if not parts:
                continue
            eid = doc + "/" + chunk["id"]
            labels = chunk.get("questions") or []
            if isinstance(labels, str):
                labels = labels.splitlines()
            labels = [q.strip() for q in labels if isinstance(q, str) and q.strip()]
            signature = normalize(content) or chunk.get("asset_sha256", eid)
            original = exact.setdefault(signature, eid)
            evidence[eid] = {
                "id": eid,
                "doc": doc,
                "kb": document["kb"],
                "name": name,
                "chunk_id": chunk["id"],
                "text": content,
                "sha256": digest(content),
                "parts": parts,
                "positions": chunk.get("positions") or [],
                "questions": labels,
                "duplicate_of": original if original != eid else None,
            }
            keys.add(("content", signature))
            for q in labels:
                keys.add(("question", normalize(q)))
            compact = re.sub(r"\W", "", normalize(content))[:8192]
            if len(compact) >= 32:
                shingles = {compact[i : i + 5] for i in range(len(compact) - 4)}
                shortlist = sorted(shingles, key=digest)[:4]
                for previous in sorted(set().union(*(anchors[a] for a in shortlist))):
                    other, prior = signatures[previous]
                    if len(shingles & prior) >= config["near_duplicate_threshold"] * len(shingles | prior):
                        merge(doc, other)
                        evidence[eid]["duplicate_of"] = previous
                        break
                else:
                    signatures[eid] = (doc, shingles)
                    for a in shortlist:
                        anchors[a].add(eid)
        for key in keys:
            merge(doc, families.setdefault(key, doc))
    for item in evidence.values():
        family = root(item["doc"])
        n = int(digest(str(config["seed"]) + family)[:8], 16) % 100
        split = "train" if n < config["train_percent"] else "validation" if n < config["train_percent"] + config["validation_percent"] else "test"
        item.update(group_id=family, split=split)
    return evidence


def preserve_partitions(db, owner, evidence):
    families = defaultdict(list)
    for item in evidence.values():
        families[item["group_id"]].append(item)
    for family, items in families.items():
        fingerprints = {digest(normalize(i["text"])) for i in items if i["text"]}
        fingerprints.update("doc:" + i["doc"] for i in items)
        assigned = set()
        for fingerprint in fingerprints:
            row = db.execute("SELECT split FROM partition WHERE owner=? AND fingerprint=?", (owner, fingerprint)).fetchone()
            if row:
                assigned.add(row[0])
        if len(assigned) > 1:
            raise FactoryError("来源家族跨越已冻结分区，需拆分或清理重复来源")
        split = next(iter(assigned)) if assigned else items[0]["split"]
        for item in items:
            item["split"] = split
        for fingerprint in fingerprints:
            db.execute("INSERT OR IGNORE INTO partition VALUES(?,?,?,?)", (owner, fingerprint, family, split))


def overlaps_positive(left, right, threshold=0.85):
    left, right = normalize(left), normalize(right)
    if not left or not right:
        return False
    if left == right or (min(len(left), len(right)) >= 32 and (left in right or right in left)):
        return True
    a = {left[i : i + 5] for i in range(max(0, len(left) - 4))}
    b = {right[i : i + 5] for i in range(max(0, len(right) - 4))}
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= threshold
