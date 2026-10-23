"""AI task routes. Streaming reports a candidate; it does not save the chapter."""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.broker import encode_sse
from app.ai.runtime import AiRuntime
from app.api.deps import get_db, require_session
from app.core.config import get_settings
from app.schemas.ai import AiTaskAccept, AiTaskAcceptResponse, AiTaskCreate, AiTaskResponse
from app.schemas.context import CompiledContext, ContextCompileRequest
from app.services import ai_tasks as ai_service

router = APIRouter(prefix="/ai/tasks", tags=["ai"], dependencies=[Depends(require_session)])


def get_ai_runtime(request: Request) -> AiRuntime:
    return cast(AiRuntime, request.app.state.ai_runtime)


@router.post("/context/compile", response_model=CompiledContext)
def compile_task_context(
    payload: ContextCompileRequest,
    session: Annotated[Session, Depends(get_db)],
) -> CompiledContext:
    return ai_service.preview_context(session, payload)


@router.post("", response_model=AiTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: AiTaskCreate,
    session: Annotated[Session, Depends(get_db)],
    runtime: Annotated[AiRuntime, Depends(get_ai_runtime)],
) -> AiTaskResponse:
    return ai_service.create_ai_task(session, payload, runtime)


@router.get("/{task_id}", response_model=AiTaskResponse)
def read_task(task_id: str, session: Annotated[Session, Depends(get_db)]) -> AiTaskResponse:
    return ai_service.get_ai_task(session, task_id)


@router.get("/{task_id}/context", response_model=CompiledContext)
def read_task_context(
    task_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> CompiledContext:
    return ai_service.get_task_context(session, task_id)


@router.post("/{task_id}/cancel", response_model=AiTaskResponse)
def cancel_task(
    task_id: str,
    session: Annotated[Session, Depends(get_db)],
    runtime: Annotated[AiRuntime, Depends(get_ai_runtime)],
) -> AiTaskResponse:
    return ai_service.cancel_ai_task(session, task_id, runtime)


@router.get("/{task_id}/events")
def stream_task_events(
    task_id: str,
    session: Annotated[Session, Depends(get_db)],
    runtime: Annotated[AiRuntime, Depends(get_ai_runtime)],
) -> StreamingResponse:
    ai_service.get_ai_task(session, task_id)
    heartbeat = get_settings().sse_heartbeat_seconds

    def frames() -> Iterator[str]:
        for event, data in runtime.broker.iter_events(task_id, heartbeat):
            yield encode_sse(event, data)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/accept", response_model=AiTaskAcceptResponse)
def accept_task(
    task_id: str,
    payload: AiTaskAccept,
    session: Annotated[Session, Depends(get_db)],
    runtime: Annotated[AiRuntime, Depends(get_ai_runtime)],
) -> AiTaskAcceptResponse:
    task, chapter = ai_service.accept_ai_task(session, task_id, payload, runtime)
    return AiTaskAcceptResponse(task=task, chapter=chapter)


@router.post("/{task_id}/reject", response_model=AiTaskResponse)
def reject_task(task_id: str, session: Annotated[Session, Depends(get_db)]) -> AiTaskResponse:
    return ai_service.reject_ai_task(session, task_id)
