"""Recipe definitions and the dependency graph derived from them.

Dependencies come from three places only: Jinja references in a prompt, the
``multimodal_context`` list, and names mentioned in ``params``. A column never
states its own dependencies, because a hand-written list drifts from the prompt.
"""

from typing import Any, Literal

from jinja2 import TemplateError
from pydantic import BaseModel, ConfigDict, Field

from datafactory.engine.templating import template_roots

ColumnType = Literal[
    "sampler",
    "expression",
    "llm_text",
    "llm_structured",
    "llm_judge",
    "embedding",
    "retrieval",
    "rerank_score",
    "false_negative_check",
    "validator",
    "processor",
    "plugin",
    "asset_ref",
]

# Columns that run once over the whole dataset, after every batch has finished.
GLOBAL_KINDS = {"split", "hard_negative_select", "exact_dedup", "minhash_dedup", "embedding_dedup"}
# Columns that run once per batch rather than once per row.
BATCH_TYPES = {"embedding"}

_SEED_NAMES = {"seed", "row_key"}


class RecipeError(ValueError):
    """A recipe that cannot be saved or run. ``problems`` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


class Column(BaseModel):
    """One declared column. ``params`` is interpreted by the column's type."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: ColumnType
    params: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    prompt: str | None = None
    system_prompt: str | None = None
    multimodal_context: list[str] = Field(default_factory=list)
    output_schema: dict | None = None
    on_error: Literal["drop_row", "null", "fail_run"] = "drop_row"


class SeedSource(BaseModel):
    """Where the rows come from. A snapshot is frozen, so the input never moves."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ragflow_snapshot", "release", "upload"]
    snapshot_id: str | None = None
    unit: Literal["segment", "adjacent_bundle", "semantic_bundle", "cross_doc_bundle"] = "segment"
    filters: dict[str, Any] = Field(default_factory=dict)
    sample: dict[str, Any] = Field(default_factory=dict)


class ModelRef(BaseModel):
    """A role pointing at a RAGFlow model id. The platform stores no credentials."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    gen_conf: dict[str, Any] = Field(default_factory=dict)


class Recipe(BaseModel):
    """A complete recipe. Versions of this are immutable once a run references them."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    task_type: Literal["retrieval", "rerank", "sft", "preference"] = "retrieval"
    seed: SeedSource
    models: dict[str, ModelRef] = Field(default_factory=dict)
    columns: list[Column] = Field(max_length=128)
    processors: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    budget: dict[str, Any] = Field(default_factory=dict)
    run: dict[str, Any] = Field(default_factory=dict)


def dependencies_of(column: Column) -> set[str]:
    """The column names this column reads. Seed fields are not dependencies."""
    found: set[str] = set()
    for template in (column.prompt, column.system_prompt):
        if template:
            found.update(template_roots(template))
    for ref in column.multimodal_context:
        found.add(ref.split(".", 1)[0])
    if "expr" in column.params:
        expr = column.params["expr"]
        found.update(template_roots(expr if "{{" in expr or "{%" in expr else "{{ " + expr + " }}"))
    for key in ("field", "query", "targets", "exclude", "scores", "positives", "candidates"):
        value = column.params.get(key, [])
        for ref in value if isinstance(value, list) else [value]:
            if isinstance(ref, str):
                found.add(ref.split(".", 1)[0])
    defaults = {}
    if column.type in {"retrieval", "rerank_score"}:
        defaults["query"] = "qa"
    if column.params.get("kind") == "hard_negative_select":
        defaults = {"positives": "qa", "scores": "teacher_scores", "candidates": "candidates"}
    if column.type == "false_negative_check":
        defaults = {"positives": "qa", "scores": "teacher_scores"}
    for key, value in defaults.items():
        if key not in column.params:
            found.add(value)
    return found - _SEED_NAMES


def column_order(recipe: Recipe) -> list[Column]:
    """Columns in execution order. A cycle raises with the names involved."""
    by_name = {column.name: column for column in recipe.columns}
    pending = {column.name: dependencies_of(column) & set(by_name) for column in recipe.columns}
    ordered: list[Column] = []
    while pending:
        ready = sorted(name for name, deps in pending.items() if not deps)
        if not ready:
            raise RecipeError([f"Columns depend on each other in a cycle: {', '.join(sorted(pending))}."])
        for name in ready:
            ordered.append(by_name[name])
            del pending[name]
            for deps in pending.values():
                deps.discard(name)
    return ordered


def granularity(column: Column) -> Literal["cell", "batch", "global"]:
    """How widely a column runs. Global columns wait until every batch is done."""
    kind = column.params.get("kind")
    if kind in GLOBAL_KINDS:
        return "global"
    if column.type in BATCH_TYPES:
        return "batch"
    return "cell"


def validate_recipe(recipe: Recipe) -> list[str]:
    """Every reason a recipe cannot run. An empty list means it can."""
    problems: list[str] = []
    if not isinstance(recipe.run.get("batch_size", 64), int) or not 1 <= recipe.run.get("batch_size", 64) <= 64:
        problems.append("run.batch_size must be an integer between 1 and 64.")
    if type(recipe.run.get("seed", 1)) is not int or not -(2**31) <= recipe.run.get("seed", 1) < 2**31:
        problems.append("run.seed must be a signed 32-bit integer.")
    for key in ("max_invocations", "max_tokens"):
        if key in recipe.budget and (type(recipe.budget[key]) is not int or not 1 <= recipe.budget[key] < 2**31):
            problems.append(f"budget.{key} must be a positive 32-bit integer.")
    if recipe.budget.get("on_exceed", "pause") not in {"pause", "fail"}:
        problems.append("budget.on_exceed must be pause or fail.")
    names = [column.name for column in recipe.columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append(f"Column names are repeated: {', '.join(duplicates)}.")
    defined = set(names)
    if any(
        not name.isidentifier() or name.startswith("_") or name in _SEED_NAMES | {"segment_id", "group_key"}
        for name in names
    ):
        problems.append("Column names must be identifiers and must not overwrite engine fields.")
    for column in recipe.columns:
        try:
            missing = sorted(dependencies_of(column) - defined)
        except TemplateError as exc:
            problems.append(f"Column {column.name} has an invalid template: {exc}.")
            continue
        if missing:
            problems.append(f"Column {column.name} references undefined columns: {', '.join(missing)}.")
        if column.model and column.model not in recipe.models:
            problems.append(f"Column {column.name} uses model role {column.model}, which is not declared.")
        if column.type == "llm_structured" and not column.output_schema:
            problems.append(f"Column {column.name} is llm_structured but has no output schema.")
        if column.type == "sampler":
            problems.extend(_sampler_problems(column))
    try:
        column_order(recipe)
    except RecipeError as exc:
        problems.extend(exc.problems)
    except TemplateError:
        pass
    return problems


def _sampler_problems(column: Column) -> list[str]:
    kind = column.params.get("kind")
    if kind == "category":
        values = column.params.get("values", {})
        if not values:
            return [f"Sampler {column.name} has no values."]
        total = sum(values.values())
        if abs(total - 1.0) > 0.01:
            return [f"Sampler {column.name} weights sum to {total}, not 1."]
    return []
