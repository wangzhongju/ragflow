"""Project membership: owners, editors, and everyone else."""

import pytest

from datafactory.core.errors import BadRequest, Forbidden
from datafactory.store.projects import Member, ProjectRepository

pytestmark = pytest.mark.usefixtures("session")


async def test_creator_is_owner_and_strangers_see_nothing(session):
    repo = ProjectRepository(session)
    project = await repo.create("u1", "Laws", "statute corpus")

    assert project.id.startswith("prj_")
    assert project.role == "owner"
    assert [item.id for item in await repo.list_for("u1")] == [project.id]
    assert await repo.list_for("u2") == []
    with pytest.raises(Forbidden):
        await repo.get(project.id, "u2")


async def test_blank_name_is_rejected(session):
    with pytest.raises(BadRequest):
        await ProjectRepository(session).create("u1", "  ", "")


async def test_editor_renames_but_cannot_delete_or_change_members(session):
    repo = ProjectRepository(session)
    project = await repo.create("u1", "Laws", "")
    await repo.set_members(project.id, "u1", [Member("u1", "owner"), Member("u2", "editor")])

    renamed = await repo.rename(project.id, "u2", "Regulations", None)
    assert renamed.name == "Regulations"
    assert renamed.role == "editor"

    with pytest.raises(Forbidden):
        await repo.delete(project.id, "u2")
    with pytest.raises(Forbidden):
        await repo.set_members(project.id, "u2", [Member("u2", "owner")])


async def test_owner_cannot_leave_the_project_ownerless(session):
    repo = ProjectRepository(session)
    project = await repo.create("u1", "Laws", "")
    with pytest.raises(BadRequest):
        await repo.set_members(project.id, "u1", [Member("u2", "owner")])

    members = await repo.members(project.id, "u1")
    assert [(member.user_id, member.role) for member in members] == [("u1", "owner")]


async def test_viewer_cannot_rename(session):
    repo = ProjectRepository(session)
    project = await repo.create("u1", "Laws", "")
    await repo.set_members(project.id, "u1", [Member("u1", "owner"), Member("u2", "viewer")])
    with pytest.raises(Forbidden):
        await repo.rename(project.id, "u2", "Other", None)


async def test_delete_removes_membership(session):
    repo = ProjectRepository(session)
    project = await repo.create("u1", "Laws", "")
    await repo.delete(project.id, "u1")
    assert await repo.list_for("u1") == []
