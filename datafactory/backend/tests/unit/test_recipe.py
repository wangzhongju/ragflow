"""Recipes: inferred dependencies, deterministic sampling and column execution."""

import json

import httpx

from datafactory.core.settings import GatewaySettings
from datafactory.engine.cache import cache_key
from datafactory.engine.columns import execute
from datafactory.engine.recipe import (
    Column,
    ModelRef,
    Recipe,
    SeedSource,
    column_order,
    dependencies_of,
    granularity,
    validate_recipe,
)
from datafactory.engine.sampling import draw
from datafactory.gateway.client import GatewayClient


def _recipe(columns: list[Column], models: dict | None = None) -> Recipe:
    return Recipe(
        seed=SeedSource(type="ragflow_snapshot", snapshot_id="snap_1"),
        models=models or {},
        columns=columns,
    )


def test_dependencies_come_from_the_template_not_from_a_declared_list():
    column = Column(
        name="qa",
        type="llm_structured",
        model="generator",
        prompt="Write a {{ difficulty }} question of type {{ query_type }} about {{ seed.parts | render_parts }}",
        multimodal_context=["seed.images"],
        params={"exclude": ["positives"]},
        output_schema={"required": ["question"]},
    )
    # seed is the row source, not a column, so it is not a dependency.
    assert dependencies_of(column) == {"difficulty", "query_type", "positives"}


def test_a_cycle_is_rejected_with_the_columns_named():
    recipe = _recipe(
        [
            Column(name="a", type="expression", params={"expr": "{{ b }}"}),
            Column(name="b", type="expression", params={"expr": "{{ a }}"}),
        ]
    )
    problems = validate_recipe(recipe)
    assert any("cycle" in problem for problem in problems)


def test_execution_order_respects_inferred_dependencies():
    recipe = _recipe(
        [
            Column(name="qa", type="expression", params={"expr": "{{ query_type }}"}),
            Column(name="query_type", type="sampler", params={"kind": "category", "values": {"factoid": 1}}),
        ]
    )
    assert [column.name for column in column_order(recipe)] == ["query_type", "qa"]


def test_a_missing_model_role_is_reported():
    recipe = _recipe([Column(name="qa", type="llm_text", model="generator", prompt="hi")])
    problems = validate_recipe(recipe)
    assert any("generator" in problem for problem in problems)


def test_literals_in_parameters_are_not_column_references():
    recipe = _recipe([Column(name="kind", type="sampler", params={"kind": "category", "values": {"factoid": 1}})])
    assert validate_recipe(recipe) == []


def test_self_references_and_invalid_templates_are_reported():
    for expression in ("{{ query }}", "{{ ! invalid }}"):
        recipe = _recipe([Column(name="query", type="expression", params={"expr": expression})])
        assert validate_recipe(recipe)


def test_sampler_weights_must_sum_to_one():
    recipe = _recipe(
        [Column(name="difficulty", type="sampler", params={"kind": "category", "values": {"2": 0.3, "3": 0.3}})]
    )
    assert any("sum" in problem for problem in validate_recipe(recipe))


def test_the_same_row_always_draws_the_same_value():
    column = Column(
        name="query_type", type="sampler", params={"kind": "category", "values": {"factoid": 0.5, "how_to": 0.5}}
    )
    first = [draw(column, 20261112, f"row_{i}") for i in range(20)]
    second = [draw(column, 20261112, f"row_{i}") for i in range(20)]
    assert first == second
    assert set(first) <= {"factoid", "how_to"}


def test_a_different_seed_changes_the_draw():
    column = Column(name="difficulty", type="sampler", params={"kind": "category", "values": {"2": 0.5, "3": 0.5}})
    one = [draw(column, 1, f"row_{i}") for i in range(30)]
    other = [draw(column, 2, f"row_{i}") for i in range(30)]
    assert one != other


def test_global_columns_wait_for_every_batch():
    column = Column(name="negatives", type="processor", params={"kind": "hard_negative_select"})
    assert granularity(column) == "global"
    assert granularity(Column(name="dedup", type="processor", params={"kind": "embedding_dedup"})) == "global"


def test_the_cache_key_changes_when_a_dependency_changes():
    column = Column(name="qa", type="expression", params={"expr": "{{ query_type }}"})
    base = cache_key(column, {"query_type": "factoid"}, "", {}, "")
    changed = cache_key(column, {"query_type": "how_to"}, "", {}, "")
    assert base != changed
    assert base == cache_key(column, {"query_type": "factoid"}, "", {}, "")


def _gateway(captured: dict) -> GatewayClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["inputs"] = body["inputs"]
        captured.setdefault("calls", []).append(body)
        if body["op"] == "chat":
            output = {"text": '{"question": "What notice is required?", "positives": ["seg_1"]}'}
        elif body["op"] == "embed_documents":
            output = {"vectors": [[1.0, 0.0] if "notice" in text else [0.0, 1.0] for text in body["inputs"]["texts"]]}
        else:
            output = {"scores": [0.2, 0.9]}
        data = {"outputs": output, "usage": {}, "latency_ms": 5, "model_fingerprint": "fp"}
        return httpx.Response(200, json={"code": 0, "data": data, "message": ""}, headers={"X-Gateway-Version": "1"})

    settings = GatewaySettings(
        gateway_base_url="http://gateway.test/api/v1", gateway_service_key="k", gateway_version="1"
    )
    return GatewayClient(settings, "u1", transport=httpx.MockTransport(handler))


async def test_structured_output_is_parsed_and_checked(column_context):
    captured: dict = {}
    column = Column(
        name="qa",
        type="llm_structured",
        model="generator",
        prompt="Type {{ query_type }}",
        output_schema={"required": ["question", "positives"]},
    )
    recipe = _recipe([column], {"generator": ModelRef(model_id="tm_qwen")})
    rows = await execute(
        column, [{"row_key": "r1", "query_type": "factoid"}], recipe, await column_context(_gateway(captured)), 1
    )
    assert rows[0]["qa"]["question"] == "What notice is required?"
    assert "factoid" in captured["inputs"]["history"][0]["content"]


async def test_a_schema_miss_drops_the_row_by_default(column_context):
    column = Column(
        name="qa", type="llm_structured", model="generator", prompt="x", output_schema={"required": ["answer"]}
    )
    recipe = _recipe([column], {"generator": ModelRef(model_id="tm_qwen")})
    rows = await execute(column, [{"row_key": "r1"}], recipe, await column_context(_gateway({})), 1)
    assert rows[0]["_dropped"] is True


async def test_dedup_keeps_the_first_row(column_context):
    captured: dict = {}
    column = Column(
        name="kept",
        type="processor",
        params={"kind": "embedding_dedup", "field": "text", "threshold": 0.8, "model": "embedder"},
    )
    recipe = _recipe([column], {"embedder": ModelRef(model_id="tm_embed")})
    rows = [
        {"row_key": "r1", "text": "notice before revocation of the licence"},
        {"row_key": "r2", "text": "notice before revocation of the licence"},
        {"row_key": "r3", "text": "sourdough needs wild yeast"},
    ]
    kept = await execute(column, rows, recipe, await column_context(_gateway(captured)), 1)
    assert [row["row_key"] for row in kept] == ["r1", "r3"]
    assert captured["calls"][0]["op"] == "embed_documents"


async def test_a_filter_expression_drops_rows(column_context):
    column = Column(name="passed", type="processor", params={"kind": "filter", "expr": "score >= 7"})
    rows = [{"row_key": "r1", "score": 8}, {"row_key": "r2", "score": 3}]
    kept = await execute(column, rows, _recipe([column]), await column_context(_gateway({})), 1)
    assert [row["row_key"] for row in kept] == ["r1"], [dict(row) for row in kept]
