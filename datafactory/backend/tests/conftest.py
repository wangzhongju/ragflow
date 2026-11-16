"""Shared fixtures for the unit suite.

The database is SQLite in memory. The gateway is a scripted transport, so no
test opens a socket.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from datafactory.app.auth import session_cookie
from datafactory.app.main import create_app
from datafactory.core.settings import Settings
from datafactory.store.objects import MemoryObjectStore
from datafactory.store.tables import Base


@pytest.fixture
def settings() -> Settings:
    """Development settings aimed at local, dev-named resources."""
    return Settings(
        env="dev",
        host="localhost",
        database_url="sqlite+aiosqlite://",
        redis_prefix="df:dev:localhost:",
        minio_bucket="datafactory-dev-localhost",
        gateway_base_url="http://gateway.test/api/v1",
        gateway_service_key="test-key",
        session_secret="unit-test-session-secret-32-characters",
    )


@pytest.fixture
async def app(settings: Settings):
    """An application whose schema exists and whose lifespan is running."""
    application = create_app(settings, objects=MemoryObjectStore())
    async with application.router.lifespan_context(application):
        async with application.state.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def session(app) -> AsyncIterator[AsyncSession]:
    """A database session outside the request cycle, for arranging rows."""
    async with app.state.sessions() as db:
        yield db


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """An HTTP client signed in as user ``u1`` through the session cookie."""
    transport = ASGITransport(app=app)
    _name, value = session_cookie("u1", app.state.settings.session_secret)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={_name: value}) as http:
        yield http


@pytest.fixture
def column_context(session, app):
    from datafactory.core.ids import new_id
    from datafactory.engine.columns import ColumnContext
    from datafactory.engine.model_client import ModelClient
    from datafactory.store.runs import RunStore
    from datafactory.store.tables import RunRow

    async def create(gateway):
        run = RunRow(id=new_id("run"), project_id="p", recipe_id="r", snapshot_id="s", status="running")
        session.add(run)
        await session.commit()
        return ColumnContext(gateway, ModelClient(gateway, RunStore(session, app.state.objects, run.id, 0)))

    return create
