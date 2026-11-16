"""Deterministic sampling.

A sampler's draw is ``hash(run seed, row key, column name)``, so the same row
gets the same value no matter which batch it lands in or how many times the run
is resumed.
"""

import hashlib
import random

from datafactory.engine.recipe import Column


def draw(column: Column, run_seed: int, row_key: str) -> object:
    """One value for one row. The column must be a sampler."""
    rng = random.Random(_seed(run_seed, row_key, column.name))
    kind = column.params.get("kind", "category")
    if kind == "category":
        return _weighted(rng, column.params["values"])
    if kind == "uniform":
        low = column.params.get("low", 0)
        high = column.params["high"]
        return rng.randint(low, high) if isinstance(high, int) else rng.uniform(low, high)
    if kind == "bernoulli":
        return rng.random() < column.params.get("p", 0.5)
    raise ValueError(f"Sampler {column.name} has unknown kind {kind}.")


def _weighted(rng: random.Random, values: dict) -> object:
    roll = rng.random() * sum(values.values())
    covered = 0.0
    chosen = next(iter(values))
    for value, weight in values.items():
        covered += weight
        chosen = value
        if roll <= covered:
            break
    return _coerce(chosen)


def _coerce(value: object) -> object:
    """JSON object keys are strings; numeric categories come back as numbers."""
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


def _seed(run_seed: int, row_key: str, column: str) -> int:
    digest = hashlib.sha256(f"{run_seed}|{row_key}|{column}".encode()).digest()
    return int.from_bytes(digest[:8], "big")
