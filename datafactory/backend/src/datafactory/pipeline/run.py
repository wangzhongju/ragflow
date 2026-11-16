"""Execute declared columns and materialize retrieval samples from their outputs."""

from time import monotonic

from datafactory.engine.columns import ColumnContext, execute
from datafactory.engine.mining import check_gates, split_rows
from datafactory.engine.recipe import Column, Recipe, RecipeError, column_order, granularity, validate_recipe
from datafactory.store.runs import RunStore


def build_seed_rows(segments: list[dict], limit: int) -> list[dict]:
    if limit < 1:
        raise ValueError("Seed limit must be positive.")
    corpus = {segment["id"]: segment for segment in segments}
    return [
        {
            "row_key": segment["id"],
            "segment_id": segment["id"],
            "seed": {**segment, "images": [part for part in segment["parts"] if part["type"] == "image"]},
            "group_key": segment.get("family_id") or segment["origin"]["doc_id"],
            "_corpus": corpus,
        }
        for segment in segments[:limit]
    ]


async def produce(
    recipe: Recipe,
    segments: list[dict],
    context: ColumnContext,
    seed: int,
    limit: int,
    *,
    checkpoints: RunStore | None = None,
) -> list[dict]:
    problems = validate_recipe(recipe)
    if problems:
        raise RecipeError(problems)
    produced = build_seed_rows(segments, limit)
    corpus = {segment["id"]: segment for segment in segments}
    stages = column_order(recipe)
    ratios = {"train": 0.8, "val": 0.1, "test": 0.1}
    split_seed = seed
    for index, params in enumerate(recipe.processors):
        if params["kind"] == "split":
            ratios = params.get("ratios", ratios)
            split_seed = params.get("seed", seed)
        elif params["kind"] == "to_samples":
            continue
        else:
            stages.append(Column(name=f"processor_{index}", type="processor", params=params))
    size = recipe.run.get("batch_size", 64)
    if checkpoints:
        await checkpoints.plan(
            sum(1 if granularity(col) == "global" else (len(produced) + size - 1) // size for col in stages)
        )
    units = 0
    for stage, column in enumerate(stages):
        batches = (
            [produced]
            if granularity(column) == "global"
            else [produced[i : i + size] for i in range(0, len(produced), size)]
        )
        output = []
        for batch, rows in enumerate(batches):
            restored = await checkpoints.load(stage, batch) if checkpoints else None
            if restored is None:
                started = monotonic()
                restored = await execute(column, rows, recipe, context, seed)
                if checkpoints:
                    await checkpoints.save(stage, batch, column.name, restored, int((monotonic() - started) * 1000))
            output.extend({**row, "_corpus": corpus} for row in restored if not row.get("_dropped"))
            units += 1
        produced = output
    if checkpoints:
        await checkpoints.plan(units)
    samples = []
    for row in produced:
        qa = row.get("qa") or {}
        query = row.get("query", qa.get("question", ""))
        positives = qa.get("positives", [row["segment_id"]])
        negatives = row.get("negatives") or []
        suspects = set(row.get("false_negative_suspects", []))
        for column in recipe.columns:
            if column.type == "false_negative_check":
                suspects.update(row.get(column.name) or [])
        negatives = [segment_id for segment_id in negatives if segment_id not in suspects]
        corpus = row["_corpus"]
        if not isinstance(query, str) or not query.strip():
            continue
        if any(segment_id not in corpus for segment_id in positives + negatives):
            raise ValueError("Sample references a segment outside the frozen snapshot.")
        samples.append(
            {
                "row_key": row["row_key"],
                "group_key": row["group_key"],
                "query": query,
                "positives": positives,
                "negatives": negatives,
                "false_negative_suspects": sorted(suspects),
                "judge": row.get("judge") or {},
                "teacher_scores": row.get("teacher_scores") or {},
                "modality": corpus[row["segment_id"]]["modality"],
            }
        )
    return split_rows(samples, ratios, split_seed)


def release_check(samples: list[dict], snapshot_status: str) -> list[dict]:
    return [gate.__dict__ for gate in check_gates(samples, snapshot_status)]
