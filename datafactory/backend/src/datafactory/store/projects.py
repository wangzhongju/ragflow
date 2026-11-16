"""Project and membership access.

Roles, strongest first: owner, editor, reviewer, viewer. A user with no row has
no access. The numeric id of a membership row stays inside this module.
"""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datafactory.core.errors import BadRequest, Conflict, Forbidden, NotFound
from datafactory.core.idempotency import request_hash
from datafactory.core.ids import new_id
from datafactory.store.tables import ROLES, IdempotencyRow, MemberRow, ProjectRow, RecipeRow, RunRow, SnapshotRow

_RANK = {role: len(ROLES) - index for index, role in enumerate(ROLES)}


class Project:
    """A project as the rest of the platform sees it."""

    def __init__(self, id: str, name: str, description: str, owner_id: str, role: str) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.owner_id = owner_id
        self.role = role


class Member:
    """One membership."""

    def __init__(self, user_id: str, role: str) -> None:
        self.user_id = user_id
        self.role = role


class ProjectRepository:
    """Reads and writes projects for one database session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, owner_id: str, name: str, description: str, key: str = "") -> Project:
        """Create a project and make the caller its owner."""
        if not name.strip():
            raise BadRequest("A project needs a name.")
        scope = f"project:{owner_id}"
        key_hash = request_hash({"key": key})
        payload_hash = request_hash({"name": name, "description": description})
        if key:
            earlier = await self._replay(scope, key_hash, payload_hash, owner_id)
            if earlier is not None:
                return earlier
        project_id = new_id("project")
        self._session.add(ProjectRow(id=project_id, name=name.strip(), description=description, owner_id=owner_id))
        self._session.add(MemberRow(project_id=project_id, user_id=owner_id, role="owner"))
        if key:
            self._session.add(
                IdempotencyRow(
                    scope=scope,
                    key_hash=key_hash,
                    request_hash=payload_hash,
                    resource_id=project_id,
                )
            )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if key:
                earlier = await self._replay(scope, key_hash, payload_hash, owner_id)
                if earlier is not None:
                    return earlier
            raise
        return Project(project_id, name.strip(), description, owner_id, "owner")

    async def _replay(self, scope: str, key_hash: str, payload_hash: str, user_id: str) -> Project | None:
        record = await self._session.get(IdempotencyRow, (scope, key_hash))
        if record is None:
            return None
        if record.request_hash != payload_hash:
            raise Conflict("Idempotency key was already used for a different request.")
        return await self.get(record.resource_id, user_id)

    async def list_for(self, user_id: str) -> list[Project]:
        """Projects the user belongs to, most recently created first."""
        rows = await self._session.execute(
            select(ProjectRow, MemberRow.role)
            .join(MemberRow, MemberRow.project_id == ProjectRow.id)
            .where(MemberRow.user_id == user_id)
            .order_by(ProjectRow.created_at.desc())
        )
        return [
            Project(project.id, project.name, project.description, project.owner_id, role) for project, role in rows
        ]

    async def get(self, project_id: str, user_id: str) -> Project:
        """The project, when the user is a member of it."""
        role = await self.require_role(project_id, user_id, "viewer")
        row = await self._session.get(ProjectRow, project_id)
        if row is None:
            raise NotFound(f"Project {project_id} not found.")
        return Project(row.id, row.name, row.description, row.owner_id, role)

    async def rename(self, project_id: str, user_id: str, name: str, description: str | None) -> Project:
        """Change the name and, when given, the description. Editors and owners only."""
        await self.require_role(project_id, user_id, "editor")
        row = await self._session.get(ProjectRow, project_id)
        if row is None:
            raise NotFound(f"Project {project_id} not found.")
        if not name.strip():
            raise BadRequest("A project needs a name.")
        row.name = name.strip()
        if description is not None:
            row.description = description
        await self._session.commit()
        return await self.get(project_id, user_id)

    async def delete(self, project_id: str, user_id: str) -> None:
        """Delete a project. Only its owner can."""
        await self.require_role(project_id, user_id, "owner")
        for table in (SnapshotRow, RecipeRow, RunRow):
            if await self._session.scalar(select(table.id).where(table.project_id == project_id).limit(1)):
                raise Conflict("Projects containing production resources cannot be deleted.", code="project_not_empty")
        await self._session.execute(delete(MemberRow).where(MemberRow.project_id == project_id))
        await self._session.execute(delete(ProjectRow).where(ProjectRow.id == project_id))
        await self._session.commit()

    async def members(self, project_id: str, user_id: str) -> list[Member]:
        """List members. Any member may see the list."""
        await self.require_role(project_id, user_id, "viewer")
        rows = await self._session.scalars(select(MemberRow).where(MemberRow.project_id == project_id))
        return [Member(row.user_id, row.role) for row in rows]

    async def set_members(self, project_id: str, user_id: str, members: list[Member]) -> list[Member]:
        """Replace the member list. The owner keeps exactly one owner: themselves."""
        await self.require_role(project_id, user_id, "owner")
        if len({member.user_id for member in members}) != len(members):
            raise BadRequest("A user may appear only once in the member list.")
        if any(not member.user_id.strip() for member in members):
            raise BadRequest("Every member needs a user id.")
        owner_ids = [member.user_id for member in members if member.role == "owner"]
        if owner_ids != [user_id]:
            raise BadRequest("A project keeps its current owner; transfer is a separate operation.")
        for member in members:
            if member.role not in ROLES:
                raise BadRequest(f"Unknown role {member.role}.")
        await self._session.execute(delete(MemberRow).where(MemberRow.project_id == project_id))
        for member in members:
            self._session.add(MemberRow(project_id=project_id, user_id=member.user_id, role=member.role))
        await self._session.commit()
        return await self.members(project_id, user_id)

    async def require_role(self, project_id: str, user_id: str, minimum: str) -> str:
        """Raise when the user is below ``minimum``. Returns the role they hold."""
        role = await self._role(project_id, user_id)
        if role is None or _RANK[role] < _RANK[minimum]:
            raise Forbidden(f"Project {project_id} is not accessible.")
        return role

    async def _role(self, project_id: str, user_id: str) -> str | None:
        row = await self._session.scalar(
            select(MemberRow.role).where(MemberRow.project_id == project_id, MemberRow.user_id == user_id)
        )
        return row
