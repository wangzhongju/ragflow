"""The recipe engine: declared columns, an inferred graph, deterministic sampling.

A recipe is the only configuration a run executes. Columns do not declare their
dependencies by hand; the engine reads them out of the templates and the
parameters. Cycles and missing references are rejected before anything runs.
"""

from datafactory.engine.recipe import (
    Column,
    Recipe,
    RecipeError,
    column_order,
    dependencies_of,
    validate_recipe,
)

__all__ = ["Column", "Recipe", "RecipeError", "column_order", "dependencies_of", "validate_recipe"]
