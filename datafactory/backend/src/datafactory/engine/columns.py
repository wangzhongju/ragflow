"""Column execution.

Every column type runs through ``execute``. Cell columns see one row, batch
columns see the whole batch, and global columns see every row after the batches
finish. Model calls use ModelClient; retrieval uses already-accounted query vectors.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jsonschema

from datafactory.core.execution import BilledUnknown, BudgetExceeded, RunInterrupted
from datafactory.domain.content import ContentPart
from datafactory.domain.fingerprint import jaccard, minhash_of, normalize
from datafactory.engine.mining import Candidate, mine_negatives
from datafactory.engine.model_client import ModelInvoker
from datafactory.engine.recipe import Column, Recipe, granularity
from datafactory.engine.sampling import draw
from datafactory.engine.templating import sandbox
from datafactory.gateway.client import GatewayClient


@dataclass
class ColumnContext:
    gateway: GatewayClient
    models: ModelInvoker


Row = dict[str, Any]


class ExecutionError(RuntimeError):
    """A cell failed. The column's ``on_error`` decides what happens to the row."""


async def execute(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext, run_seed: int) -> list[Row]:
    """Run one column over rows, returning the rows with the column filled in.

    Rows are not mutated. A column that drops rows returns fewer of them.
    """
    scope = granularity(column)
    if column.type == "processor" and scope == "cell":
        scope = "batch"
    if scope == "cell":
        return [await _cell(column, row, recipe, context, run_seed) for row in rows]
    handler = _BATCH.get(column.params.get("kind", column.type))
    if handler is None:
        raise ExecutionError(f"Column {column.name} has no executor for kind {column.params.get('kind', column.type)}.")
    return await handler(column, rows, recipe, context)


async def _cell(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Row:
    try:
        value = await _CELL[column.type](column, row, recipe, context, run_seed)
    except (BilledUnknown, BudgetExceeded, RunInterrupted):
        raise
    except Exception as exc:
        if column.on_error == "fail_run":
            raise ExecutionError(f"Column {column.name} failed on {row.get('row_key')}: {exc}") from exc
        row = {**row, "_errors": [*row.get("_errors", []), {"column": column.name, "message": str(exc)[:2000]}]}
        value = None if column.on_error == "null" else _DROP
    if value is _DROP:
        return {**row, column.name: None, "_dropped": True}
    return {**row, column.name: value}


_DROP = object()


async def _sampler(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    return draw(column, run_seed, row["row_key"])


async def _expression(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    env = sandbox()
    template = env.from_string(column.params["expr"])
    return template.render(**row)


async def _llm_text(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    if column.model is None:
        raise ValueError("A model role is required.")
    model = recipe.models[column.model]
    rendered = _render(column.prompt or "", row)
    result = await context.models.invoke(
        model.model_id,
        "chat",
        {
            "system": _render(column.system_prompt or "", row),
            "history": [{"role": "user", "content": rendered}],
            "images": _images(column, row),
        },
        model.gen_conf,
        column=column.name,
        row_key=row["row_key"],
    )
    return result.outputs.get("text", "")


async def _llm_structured(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    text = await _llm_text(column, row, recipe, context, run_seed)
    parsed = _parse_json(text)
    _check_schema(parsed, column.output_schema or {})
    return parsed


async def _llm_judge(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    return await _llm_structured(column, row, recipe, context, run_seed)


async def _retrieval(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    params = column.params
    query = _lookup(row, params.get("query", "qa"))
    text = query.get("question") if isinstance(query, dict) else str(query)
    kb_ids = params.get("kb_ids") or [row["seed"]["origin"]["kb_id"]]
    datasets = {item.id: item for item in await context.gateway.list_datasets()}
    profiles = {(datasets[kb].tenant_embd_id, datasets[kb].vector_dim) for kb in kb_ids}
    if len(profiles) != 1 or not next(iter(profiles))[0]:
        raise ValueError("Dense search requires a shared, resolved embedding model and dimension.")
    model_id, _ = next(iter(profiles))
    if model_id is None:
        raise ValueError("The embedding model is not resolved.")
    encoded = await context.models.invoke(
        model_id,
        "embed_query",
        {"text": text},
        column=column.name,
        row_key=row["row_key"],
    )
    found = await context.gateway.search_dense(
        kb_ids,
        {"vector": encoded.outputs["vector"]},
        params.get("top_k", 100),
        {"exclude_chunk_ids": _chunk_ids(row, params.get("exclude", []))},
        params.get("min_score", 0.0),
    )
    by_origin = {segment["origin"]["chunk_id"]: segment for segment in row.get("_corpus", {}).values()}
    return [
        {"segment_id": by_origin[hit.chunk_id]["id"], "chunk_id": hit.chunk_id, "score": hit.score, "rank": rank}
        for rank, hit in enumerate(found.hits, 1)
        if hit.chunk_id in by_origin
    ]


async def _rerank(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    if column.model is None:
        raise ValueError("A model role is required.")
    model = recipe.models[column.model]
    targets = column.params.get("targets", [])
    corpus = row.get("_corpus", {})
    ids = []
    for target in targets:
        values = _lookup(row, target) or []
        for value in values if isinstance(values, list) else [values]:
            segment_id = value.get("segment_id") if isinstance(value, dict) else value
            if segment_id not in corpus:
                raise ValueError("Teacher target is outside the frozen snapshot.")
            if segment_id not in ids:
                ids.append(segment_id)
    documents = [_segment_text(corpus[segment_id]) for segment_id in ids]
    query = _lookup(row, column.params.get("query", "qa.question"))
    result = await context.models.invoke(
        model.model_id,
        "rerank",
        {"query": query, "texts": documents},
        model.gen_conf,
        column=column.name,
        row_key=row["row_key"],
    )
    return {
        "scores": dict(zip(ids, result.outputs["scores"], strict=True)),
        "model_fingerprint": result.model_fingerprint,
    }


async def _validator(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    rule = column.params.get("rule")
    if rule == "non_empty":
        return bool(_lookup(row, column.params["field"]))
    if rule == "min_length":
        return len(str(_lookup(row, column.params["field"]) or "")) >= column.params["value"]
    raise ValueError(f"Validator {column.name} has unknown rule {rule}.")


async def _false_negative(column: Column, row: Row, recipe: Recipe, context: ColumnContext, run_seed: int) -> Any:
    """Candidates a teacher scored above the threshold, which are likely false negatives."""
    threshold = column.params.get("teacher_threshold", 0.8)
    result = _lookup(row, column.params.get("scores", "teacher_scores")) or {}
    scores = result.get("scores", {})
    positives = _lookup(row, column.params.get("positives", "qa.positives")) or []
    if not positives or any(segment_id not in scores for segment_id in positives):
        raise ValueError("False-negative checks require teacher scores for every positive.")
    threshold = min(threshold, min(scores[segment_id] for segment_id in positives) * 0.9)
    return [segment_id for segment_id, score in scores.items() if segment_id not in positives and score >= threshold]


def _render(template: str, row: Row) -> str:
    env = sandbox()
    return env.from_string(template).render(**row)


def _images(column: Column, row: Row) -> list[str]:
    found = []
    for ref in column.multimodal_context:
        value = row
        for step in ref.split("."):
            value = value.get(step, {}) if isinstance(value, dict) else {}
        if isinstance(value, list):
            found.extend(
                item.get("asset_id") for item in value if isinstance(item, dict) and item.get("type") == "image"
            )
    return found


def _parse_json(text: str) -> Any:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The model response did not contain a JSON object.")
    return json.loads(text[start : end + 1])


def _check_schema(value: Any, schema: dict) -> None:
    """The whole JSON Schema, not just the required keys."""
    if not schema:
        return
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Structured output does not match its schema: {exc.message}.") from exc


_CELL: dict[str, Callable] = {
    "sampler": _sampler,
    "expression": _expression,
    "llm_text": _llm_text,
    "llm_structured": _llm_structured,
    "llm_judge": _llm_judge,
    "retrieval": _retrieval,
    "rerank_score": _rerank,
    "validator": _validator,
    "false_negative_check": _false_negative,
    "asset_ref": _expression,
}


async def _exact_dedup(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    """Drop rows whose field normalizes to a text already kept. Order is the run order."""
    field = column.params.get("field", "")
    kept: list[Row] = []
    seen: set[str] = set()
    for row in rows:
        text = normalize(str(_lookup(row, field)))
        if text in seen:
            continue
        seen.add(text)
        kept.append({**row, column.name: True})
    return kept


async def _minhash_dedup(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    """Drop rows whose field is a near duplicate of an earlier row, by MinHash."""
    threshold = column.params.get("threshold", 0.8)
    field = column.params.get("field", "")
    kept: list[Row] = []
    seen: list[list[int]] = []
    for row in rows:
        signature = minhash_of([ContentPart(type="text", text=str(_lookup(row, field)))])
        if signature and any(jaccard(signature, earlier) >= threshold for earlier in seen):
            continue
        if signature:
            seen.append(signature)
        kept.append({**row, column.name: True})
    return kept


async def _embedding_dedup(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    """Drop rows whose field embeds too close to an earlier row. Order is the run order.

    The embedder is a model role named in the column's params. Cosine similarity
    is computed here; the gateway only returns vectors.
    """
    threshold = column.params.get("threshold", 0.92)
    field = column.params.get("field", "")
    model = recipe.models[column.params["model"]]
    texts = [str(_lookup(row, field)) for row in rows]
    result = await context.models.invoke(
        model.model_id,
        "embed_documents",
        {"texts": texts},
        model.gen_conf,
        column=column.name,
        row_key=json.dumps([row["row_key"] for row in rows]),
    )
    vectors = result.outputs["vectors"]
    kept: list[Row] = []
    seen: list[list[float]] = []
    for row, vector in zip(rows, vectors, strict=True):
        if any(_cosine(vector, earlier) >= threshold for earlier in seen):
            continue
        seen.append(vector)
        kept.append({**row, column.name: True})
    return kept


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _chunk_ids(row: Row, columns: list) -> list[str]:
    """Chunk ids named by the row values of the given columns.

    ``exclude`` holds column names, not chunk ids. A column may hold one chunk
    id, a list of them, or a list of records that each carry ``chunk_id``.
    """
    found: list[str] = []
    for name in [columns] if isinstance(columns, str) else columns:
        value = _lookup(row, name)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict) and item.get("chunk_id"):
                    found.append(item["chunk_id"])
    corpus = row.get("_corpus", {})
    return [corpus[item]["origin"]["chunk_id"] if item in corpus else item for item in found]


def _lookup(row: Row, path: str) -> Any:
    value: Any = row
    for step in path.split("."):
        if isinstance(value, dict):
            value = value.get(step)
        else:
            return None
    return value


async def _filter(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    env = sandbox()
    template = env.from_string("{{ " + column.params["expr"] + " }}")
    return [row for row in rows if template.render(**row).strip().lower() in ("true", "1")]


_BATCH: dict[str, Callable] = {
    "embedding_dedup": _embedding_dedup,
    "exact_dedup": _exact_dedup,
    "minhash_dedup": _minhash_dedup,
    "filter": _filter,
}


def _segment_text(segment: dict) -> str:
    return "\n".join(part.get("text") or "" for part in segment["parts"])


async def _embedding(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    if not rows:
        return []
    if column.model is None:
        raise ValueError("A model role is required.")
    model = recipe.models[column.model]
    texts = [str(_lookup(row, column.params["field"])) for row in rows]
    result = await context.models.invoke(
        model.model_id,
        "embed_documents",
        {"texts": texts},
        model.gen_conf,
        column=column.name,
        row_key=json.dumps([row["row_key"] for row in rows]),
    )
    return [
        {**row, column.name: {"vector": vector, "model_fingerprint": result.model_fingerprint}}
        for row, vector in zip(rows, result.outputs["vectors"], strict=True)
    ]


async def _hard_negatives(column: Column, rows: list[Row], recipe: Recipe, context: ColumnContext) -> list[Row]:
    output = []
    for row in rows:
        corpus = row["_corpus"]
        positives = _lookup(row, column.params.get("positives", "qa.positives")) or []
        scores = _lookup(row, column.params.get("scores", "teacher_scores")) or {}
        scores = scores.get("scores", {})
        if not positives or any(segment_id not in scores for segment_id in positives):
            raise ValueError("Hard-negative selection requires teacher scores for every positive.")
        candidates = []
        for hit in _lookup(row, column.params.get("candidates", "candidates")) or []:
            segment = corpus[hit["segment_id"]]
            if segment["id"] not in scores:
                raise ValueError("Hard-negative selection requires a teacher score for every candidate.")
            candidates.append(
                Candidate(
                    chunk_id=segment["id"],
                    score=scores[segment["id"]],
                    rank=hit["rank"],
                    teacher_score=scores[segment["id"]],
                    minhash=segment.get("minhash", []),
                    parent_chunk_id=segment.get("parent_segment_id") or "",
                    text=_segment_text(segment),
                )
            )
        mined = mine_negatives(
            candidates,
            set(positives),
            min(scores[item] for item in positives),
            [corpus[item].get("minhash", []) for item in positives],
            strategy=column.params.get("strategy", "topk_percpos"),
            n=column.params.get("n", 7),
            max_ratio_to_pos=column.params.get("max_ratio_to_pos", 0.95),
            positive_parent_ids={corpus[item].get("parent_segment_id") for item in positives} - {None},
            positive_texts=[_segment_text(corpus[item]) for item in positives],
        )
        output.append(
            {
                **row,
                column.name: [item.chunk_id for item in mined.negatives],
                "false_negative_suspects": [item.chunk_id for item in mined.false_negative_suspects],
            }
        )
    return output


_BATCH.update({"embedding": _embedding, "hard_negative_select": _hard_negatives})
