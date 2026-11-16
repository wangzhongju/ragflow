"""Application factory.

``create_app`` builds the FastAPI app from the environment. The environment
guard runs while settings load, so a development process pointed at production
resources never starts serving.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from datafactory.app.auth import read_cookie
from datafactory.app.routes import router
from datafactory.core.errors import DFError
from datafactory.core.logging import configure_logging
from datafactory.core.settings import Settings, load_settings
from datafactory.store.db import make_engine, make_session_factory
from datafactory.store.objects import MinioObjectStore


def create_app(settings: Settings | None = None, *, objects=None) -> FastAPI:
    """Build the application. Tests pass settings; the process reads the environment."""
    configure_logging()
    resolved = settings or load_settings()
    if len(resolved.session_secret) < 32:
        raise ValueError("DF_SESSION_SECRET must contain at least 32 characters.")
    if objects is None and (not resolved.minio_access_key or not resolved.minio_secret_key):
        raise ValueError("DF_MINIO_ACCESS_KEY and DF_MINIO_SECRET_KEY are required for durable asset storage.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved)
        app.state.engine = engine
        app.state.sessions = make_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="DataFactory", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.objects = objects if objects is not None else MinioObjectStore(resolved)

    @app.middleware("http")
    async def session_scope(request: Request, call_next):
        """Open one database session per request and read the session cookie."""
        request.scope["df_user_id"] = read_cookie(request, request.app.state.settings.session_secret)
        sessions = getattr(request.app.state, "sessions", None)
        if sessions is None:
            return await call_next(request)
        async with sessions() as session:
            request.state.session = session
            return await call_next(request)

    @app.exception_handler(DFError)
    async def on_error(_request: Request, exc: DFError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})

    app.include_router(router, prefix=resolved.api_prefix)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "env": resolved.env}

    return app
