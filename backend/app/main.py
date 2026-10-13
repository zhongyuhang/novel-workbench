"""ASGI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.runtime import validate_runtime_configuration
from app.db.session import build_engine, build_session_factory

OPENAPI_DESCRIPTION = (
    "Personal long-form novel writing workbench. "
    "Milestone M1 covers novels, volumes, and chapters with revision locking. "
    "Autosave polish, version history, AI generation, and memory routes are not implemented yet."
)


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_configuration(settings)
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        engine = build_engine(settings.resolved_database_url)
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="AI Novel Writer",
        version=__version__,
        description=OPENAPI_DESCRIPTION,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
