"""Separate task generators over shared evidence, query and candidate contracts."""

import json
import math
import random
import re
from collections import defaultdict

from .calls import invoke
from .embedding import normalize, overlaps_positive
from .source import FactoryError, canonical, digest


def extract_json(text):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FactoryError("生成模型未返回有效 JSON，已计入调用预算") from exc


def queries(documents, evidence, ds, config, source, check):
    groups = defaultdict(list)
    for item in evidence.values():
        if item["parts"] and any(p["type"] in config["modalities"] for p in item["parts"]):
            groups[normalize(item["text"])].append(item)
    records = {}
    for items in groups.values():
        check()
        item = next((i for i in items if not i.get("duplicate_of")), None)
        if item is None:
            continue
        labels = item.get("questions", [])[: config["questions_per_chunk"]]
        origin = "existing"
        if config["query_mode"] == "llm":
            prompt = config["prompt"] + "\n返回 JSON 字符串数组，最多 " + str(config["questions_per_chunk"]) + " 个问题。\n"
            prompt += "文档：" + item["name"] + "\n章节/页位置：" + canonical(item.get("positions", [])) + "\n证据：\n" + item["text"][:5000]
            response = invoke(ds, item["id"], "generate", prompt, config, lambda prompt=prompt: source.generate(prompt, config["model_id"], config["output_tokens"]), check)
            labels = extract_json(response["text"])
            if not isinstance(labels, list) or not all(isinstance(q, str) and 3 <= len(q.strip()) <= 1024 for q in labels):
                raise FactoryError("问题 JSON 必须是非空字符串数组")
            labels = labels[: config["questions_per_chunk"]]
            origin = "llm"
        elif not labels and config["query_mode"] == "template":
            labels = ["关于“" + item["text"][:48].replace("\n", " ") + "”，" + item["name"] + "提供了哪些说明？"]
            origin = "template"
        for question in labels:
            key = (normalize(question), item["split"])
            entry = records.setdefault(key, {"query": [{"type": "text", "text": question.strip()}], "positives": [], "origin": origin})
            entry["positives"].extend(i["id"] for i in items if i["split"] == item["split"] and not i.get("duplicate_of"))
        if len(records) >= config["max_samples"]:
            break
    return list(records.values())[: config["max_samples"]]


def candidates(record, evidence, ds, config, source, check):
    positives = record["positives"]
    first = evidence[positives[0]]
    groups = defaultdict(list)
    for item in evidence.values():
        if item["split"] == first["split"] and (config["retrieval_scope"] == "snapshot" or item["doc"] == first["doc"]) and item["doc"] not in groups[item["kb"]]:
            groups[item["kb"]].append(item["doc"])
    found = []
    question = record["query"][0]["text"]
    for kb, docs in sorted(groups.items()):
        check()
        model = source.get("/datasets/" + kb).get("embedding_model") if config["retrieval"] != "lexical" else None
        # Lexical retrieval uses the live RAGFlow index, with no query embedding.
        request_key = canonical([kb, docs, question, config["retrieval"], config["rerank_id"]])
        if config["retrieval"] == "lexical":
            result = source.retrieve(kb, docs, question, config)
        else:
            result = invoke(ds, question, "retrieve", request_key, dict(config, model_id=model), lambda kb=kb, docs=docs: source.retrieve(kb, docs, question, config), check)
        for rank, hit in enumerate(result["chunks"], 1):
            eid = str(hit["document_id"]) + "/" + str(hit["id"])
            item = evidence.get(eid)
            if not item or item["split"] != first["split"] or normalize(item["text"]) != normalize(hit["content"]):
                continue
            found.append(
                {"evidence_id": eid, "method": config["retrieval"], "rank": rank, "score": hit.get("similarity"), "model_id": model, "rerank_id": config["rerank_id"], "content_sha256": item["sha256"]}
            )
    if config["rerank_id"] and found:
        unique = {hit["evidence_id"]: hit for hit in found}
        found = list(unique.values())[: config["candidate_count"]]
        texts = [evidence[hit["evidence_id"]]["text"][:4000] for hit in found]
        request_payload = canonical({"query": question, "texts": texts, "model_id": config["rerank_id"]})
        result = invoke(ds, question, "rerank", request_payload, dict(config, model_id=config["rerank_id"]), lambda: source.rerank(question, texts, config["rerank_id"]), check)
        if len(result["scores"]) != len(found):
            raise FactoryError("Rerank 返回数量与候选不一致")
        for hit, score in zip(found, result["scores"]):
            hit["rerank_score"] = score
            hit["rerank_model_name"] = result.get("model_name")
        found.sort(key=lambda hit: hit["rerank_score"], reverse=True)
    known = {normalize(evidence[eid]["text"]) for eid in positives}
    chosen = []
    uncertain = []
    required_hard = math.ceil(config["negative_count"] * config["hard_ratio"])
    for item in found if required_hard else []:
        eid = item["evidence_id"]
        text = normalize(evidence[eid]["text"])
        overlap = any(overlaps_positive(evidence[eid]["text"], evidence[p]["text"], config["near_duplicate_threshold"]) for p in positives)
        shared_query = normalize(question) in {normalize(q) for q in evidence[eid].get("questions", [])}
        if overlap or shared_query or item.get("rerank_score", -1) >= config.get("negative_relevance_ceiling", 0.8):
            uncertain.append(dict(item, exclusion_reason="positive_overlap" if overlap or shared_query else "high_relevance"))
            continue
        if text in known or evidence[eid].get("duplicate_of") in positives:
            continue
        chosen.append(item)
        known.add(text)
        if len(chosen) >= required_hard:
            break
    remaining = [
        i
        for i in evidence.values()
        if i["split"] == first["split"]
        and normalize(i["text"]) not in known
        and not any(overlaps_positive(i["text"], evidence[p]["text"], config["near_duplicate_threshold"]) for p in positives)
        and i["id"] not in {u["evidence_id"] for u in uncertain}
    ]
    random.Random(config["seed"] + int(digest(question)[:8], 16)).shuffle(remaining)
    # A hard-negative shortage remains visible. Random quota is never expanded to conceal it.
    for item in remaining[: config["negative_count"] - required_hard]:
        if normalize(item["text"]) not in known:
            chosen.append({"evidence_id": item["id"], "method": "random", "seed": config["seed"]})
            known.add(normalize(item["text"]))
    record["candidates"] = found
    record["uncertain_candidates"] = uncertain
    record["negatives"] = chosen
    record["warnings"] = ["hard_negative_shortage"] if len(chosen) < config["negative_count"] else []
    return record


class EmbeddingGenerator:
    task = "embedding"

    def payload(self, record, **context):
        return {"query": record["query"], "positives": record["positives"], "negatives": record["negatives"]}


class RerankerGenerator:
    task = "reranker"

    def payload(self, record, **context):
        labels = {eid: 2 for eid in record["positives"]}
        for candidate in record["candidates"] + record["negatives"]:
            labels.setdefault(candidate["evidence_id"], None)
        hits = {c["evidence_id"]: c for c in record["candidates"]}
        return {"query": record["query"], "candidates": [dict(hits.get(eid, {"evidence_id": eid, "method": "source"}), label=label) for eid, label in labels.items()]}


class LLMGenerator:
    task = "llm"

    def payload(self, record, **context):
        ds, config, source, check, evidence = (context[k] for k in ("ds", "config", "source", "check", "evidence"))
        question = record["query"][0]["text"]
        proof = "\n".join(evidence[i]["text"] for i in record["positives"])[:5000]
        prompt = "仅根据证据回答问题，证据不足则说明不足。返回 JSON 对象，包含 answer 字符串和 evidence_ids 数组，引用只能从给定 ID 中选。\n"
        prompt += canonical({"question": question, "evidence_ids": record["positives"], "evidence": proof})
        answer = extract_json(invoke(ds, question, "generate", prompt, config, lambda prompt=prompt: source.generate(prompt, config["model_id"], config["output_tokens"]), check)["text"])
        if (
            not isinstance(answer, dict)
            or not isinstance(answer.get("answer"), str)
            or not answer["answer"].strip()
            or not answer.get("evidence_ids")
            or not set(answer["evidence_ids"]) <= set(record["positives"])
        ):
            raise FactoryError("答案或证据引用无效")
        return {
            "messages": [{"role": "user", "content": record["query"]}, {"role": "assistant", "content": [{"type": "text", "text": answer["answer"]}]}],
            "evidence_ids": answer["evidence_ids"],
            "supervised_turns": [1],
        }


GENERATORS = {g.task: g for g in (EmbeddingGenerator(), RerankerGenerator(), LLMGenerator())}
