"""The async database engine and session factory.

Unit tests pass a SQLite URL; the running service uses MySQL through asyncmy.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from datafactory.core.settings import Settings


def make_engine(settings: Settings):
    """An async engine for the configured database.

    SQLite keeps a single connection so an in-memory database survives across
    sessions. MySQL uses a checked pool.
    """
    if settings.database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        return create_async_engine(
            settings.database_url, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """Sessions that never expire attributes on commit, so callers can read them after."""
    return async_sessionmaker(engine, expire_on_commit=False)
