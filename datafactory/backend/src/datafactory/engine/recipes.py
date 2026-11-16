"""Recipe persistence. A recipe holds a draft; versions are immutable copies."""

from pydantic import BaseModel
from sqlalchemy import select, update

from datafactory.core.errors import BadRequest, NotFound
from datafactory.core.ids import new_id
from datafactory.engine.recipe import Recipe, validate_recipe
from datafactory.store.projects import ProjectRepository
from datafactory.store.tables import RecipeRow, RecipeVersionRow


class RecipeSummary(BaseModel):
    """A recipe as listed."""

    id: str
    project_id: str
    name: str
    task: str
    status: str
    version: int


class RecipeRecord(RecipeSummary):
    """A recipe with its draft config."""

    config: dict


class RecipeRepository:
    """Reads and writes recipes for one session."""

    def __init__(self, session) -> None:
        self._session = session

    async def list_for(self, project_id: str, user_id: str) -> list[RecipeSummary]:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        rows = (await self._session.scalars(select(RecipeRow).where(RecipeRow.project_id == project_id))).all()
        return [self._summary(row) for row in rows]

    async def create(self, project_id: str, user_id: str, name: str, config: dict) -> RecipeRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        self._check(config)
        row = RecipeRow(
            id=new_id("recipe"),
            project_id=project_id,
            name=name,
            task=config.get("task_type", "retrieval"),
            config=config,
            status="draft",
            version=0,
        )
        self._session.add(row)
        await self._session.commit()
        return self._record(row)

    async def get(self, project_id: str, recipe_id: str, user_id: str) -> RecipeRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "viewer")
        return self._record(await self._row(project_id, recipe_id))

    async def update(
        self, project_id: str, recipe_id: str, user_id: str, name: str | None, config: dict | None
    ) -> RecipeRecord:
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        row = await self._row(project_id, recipe_id)
        if config is not None:
            self._check(config)
            row.config = config
        if name is not None:
            row.name = name
        await self._session.commit()
        return self._record(row)

    async def publish_version(self, project_id: str, recipe_id: str, user_id: str) -> dict:
        await ProjectRepository(self._session).require_role(project_id, user_id, "editor")
        version = await self.freeze(project_id, recipe_id)
        await self._session.commit()
        return {"id": version.id, "number": version.number}

    async def freeze(self, project_id: str, recipe_id: str) -> RecipeVersionRow:
        """Freeze under the recipe's row lock, inside the caller's transaction."""
        changed = await self._session.execute(
            update(RecipeRow)
            .where(
                RecipeRow.id == recipe_id,
                RecipeRow.project_id == project_id,
            )
            .values(version=RecipeRow.version + 1)
        )
        if changed.rowcount != 1:
            raise NotFound(f"No recipe {recipe_id}.", code="recipe_not_found")
        row = await self._row(project_id, recipe_id)
        await self._session.refresh(row)
        self._check(row.config)
        version = RecipeVersionRow(id=new_id("recipe_version"), recipe_id=row.id, number=row.version, config=row.config)
        self._session.add(version)
        await self._session.flush()
        return version

    def _check(self, config: dict) -> None:
        try:
            problems = validate_recipe(Recipe.model_validate(config))
        except ValueError as error:
            raise BadRequest(str(error)) from error
        if problems:
            raise BadRequest("; ".join(problems))

    async def _row(self, project_id: str, recipe_id: str) -> RecipeRow:
        row = await self._session.get(RecipeRow, recipe_id)
        if row is None or row.project_id != project_id:
            raise NotFound(f"No recipe {recipe_id}.", code="recipe_not_found")
        return row

    def _summary(self, row: RecipeRow) -> RecipeSummary:
        return RecipeSummary(
            id=row.id, project_id=row.project_id, name=row.name, task=row.task, status=row.status, version=row.version
        )

    def _record(self, row: RecipeRow) -> RecipeRecord:
        return RecipeRecord(**self._summary(row).model_dump(), config=row.config)
