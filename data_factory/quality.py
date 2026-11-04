"""Task-specific publication gates and sample-addressable quality findings."""

import re

from pydantic import ValidationError

from .embedding import normalize, overlaps_positive
from .schema import Sample, evidence_refs, parts_valid, query_text
from .source import FactoryError


def findings(sample, evidence):
    issues = []

    def add(code, message):
        issues.append({"code": code, "severity": "error", "message": message})

    try:
        Sample.model_validate(sample)
        parts_valid(sample["payload"].get("query", sample["payload"].get("messages", [{"content": []}])[0].get("content", [])))
    except (ValidationError, FactoryError, KeyError, IndexError, TypeError, AttributeError):
        add("schema", "样本或 ContentPart 结构无效")
        return issues
    query = query_text(sample)
    query_parts = sample["payload"].get("query", [])
    if (len(query) < 3 and not any(p.get("asset_id") for p in query_parts)) or len(query) > 4096:
        add("query", "问题长度应为 3 至 4096 字符")
    try:
        refs = evidence_refs(sample)
        if not refs or any(eid not in evidence for eid in refs):
            add("evidence", "缺少有效来源证据")
            return issues
        if any(evidence[eid]["split"] != sample["split"] for eid in refs):
            add("split", "证据跨越数据分区")
        payload = sample["payload"]
        if sample["task"] == "embedding":
            pos, neg = payload["positives"], [n["evidence_id"] for n in payload["negatives"]]
            if not pos or not neg:
                add("labels", "至少需要一个正例和一个负例")
            positive_text = {normalize(evidence[eid]["text"]) for eid in pos}
            for eid in neg:
                if normalize(evidence[eid]["text"]) in positive_text or evidence[eid].get("duplicate_of") in pos or any(overlaps_positive(evidence[eid]["text"], evidence[p]["text"]) for p in pos):
                    add("false_negative", "正负例内容重复或近重复")
            if len(set(refs)) != len(refs):
                add("duplicate", "证据 ID 重复")
        elif sample["task"] == "reranker":
            labels = [c["label"] for c in payload["candidates"]]
            if any(label not in (0, 1, 2) for label in labels) or len(labels) < 2 or len(set(labels)) < 2:
                add("labels", "需至少两个候选且存在严格等级差，全部完成 0/1/2 标注")
            positive = [c["evidence_id"] for c in payload["candidates"] if c["label"] == 2]
            negative = [c["evidence_id"] for c in payload["candidates"] if c["label"] == 0]
            if any(overlaps_positive(evidence[n]["text"], evidence[p]["text"]) for n in negative for p in positive):
                add("false_negative", "相关与不相关候选内容重复或包含")
        else:
            turns = payload["messages"]
            for turn in turns:
                parts_valid(turn["content"])
                if turn["role"] not in ("system", "user", "assistant", "tool"):
                    add("role", "对话角色无效")
            if not payload["supervised_turns"] or any(type(i) is not int or i < 0 or i >= len(turns) or turns[i]["role"] != "assistant" for i in payload["supervised_turns"]):
                add("supervision", "监督轮次应指向 assistant 消息")
        for eid in refs:
            parts_valid(evidence[eid]["parts"])
        values = [query] + [evidence[eid]["text"] for eid in refs]
        if any(re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}", v) for v in values):
            add("sensitive", "疑似密钥，需要脱敏")
    except (KeyError, TypeError, FactoryError, AttributeError, ValueError):
        add("schema", "任务 payload 或证据内容结构无效")
    return issues


def require_valid(sample, evidence):
    issues = findings(sample, evidence)
    if issues:
        raise FactoryError("；".join(i["message"] for i in issues))
