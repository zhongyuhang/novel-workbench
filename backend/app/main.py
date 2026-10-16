"""ASGI application entrypoint."""

import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.ai.broker import TaskBroker
from app.ai.runtime import AiRuntime
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.runtime import validate_runtime_configuration
from app.db.session import build_engine, build_session_factory

OPENAPI_DESCRIPTION = (
    "Personal long-form novel writing workbench. "
    "Milestone M3 adds encrypted model settings, AI generation tasks, "
    "SSE candidate streams, cancel, and accept or reject. "
    "Accepting a candidate is the only path that updates a chapter. "
    "Memory and deployment routes are not implemented yet."
)


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_configuration(settings)
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        engine = build_engine(settings.resolved_database_url)
        session_factory = build_session_factory(engine)
        executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-task")
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.ai_runtime = AiRuntime(
            session_factory=session_factory,
            broker=TaskBroker(),
            executor=executor,
            cancel_events={},
            lock=threading.Lock(),
        )
        try:
            yield
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
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
