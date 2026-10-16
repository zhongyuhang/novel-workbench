"""AI task use cases. Generation never writes the chapter; only accept does."""

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.ai.prompts import PROMPT_VERSION, TASK_LABELS, build_prompt
from app.ai.runner import run_ai_task
from app.ai.runtime import AiRuntime
from app.ai.tasks import IllegalTaskTransition, TaskStatus, transition
from app.core.content import apply_candidate_text, document_to_text
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    ModelNotConfigured,
    NotFound,
    RevisionConflict,
    TaskStateError,
)
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter
from app.repositories import catalog as catalog_repo
from app.schemas.ai import (
    AiTaskAccept,
    AiTaskCreate,
    AiTaskResponse,
)
from app.schemas.catalog import ChapterResponse
from app.services.catalog import apply_accepted_candidate
from app.services.context_builder import build_memory_context

logger = logging.getLogger("app.ai.tasks")


def create_ai_task(session: Session, payload: AiTaskCreate, runtime: AiRuntime) -> AiTaskResponse:
    novel = catalog_repo.get_novel(session, payload.novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    chapter: Chapter | None = None
    if payload.chapter_id is not None:
        chapter = catalog_repo.get_chapter(session, payload.chapter_id)
        if chapter is None or chapter.novel_id != novel.id:
            raise InvalidReference("章节不存在，或不属于这本作品。")
        if payload.target_revision is None:
            raise InvalidReference("关联章节时需要带上当前修订号。")
        if chapter.revision != payload.target_revision:
            raise RevisionConflict()
    elif payload.target_revision is not None:
        raise InvalidReference("没有章节时不能提交修订号。")

    config, provider_mode = _resolve_model(session, payload)
    if provider_mode == "mock" and payload.model_config_id and config is None:
        raise ModelConfigInvalid("找不到要使用的模拟模型。")
    chapter_text = document_to_text(chapter.content) if chapter is not None else ""
    selection = payload.selection_text or ""
    constraints = payload.constraints.model_dump() if payload.constraints is not None else None
    memory_context = build_memory_context(
        session,
        novel_id=novel.id,
        chapter_id=chapter.id if chapter is not None else None,
        instruction=payload.instruction,
        selection_text=selection,
        chapter_text=chapter_text,
    )
    prompt = build_prompt(
        task_type=payload.task_type,
        instruction=payload.instruction,
        chapter_text=chapter_text,
        selection_text=selection,
        constraints=constraints,
        memory_context=memory_context,
    )
    snapshot: dict[str, object] = {
        "instruction": payload.instruction,
        "selection_text": selection,
        "constraints": constraints,
        "target_revision": payload.target_revision,
        "chapter_text": chapter_text,
        "provider_mode": provider_mode,
        "model_name": config.model_name if config is not None else "mock",
        "display_name": config.display_name if config is not None else "模拟模型",
        "prompt": prompt,
        "mock_behavior": payload.mock_behavior or "stream",
        "mock_tokens": payload.mock_tokens,
        "mock_script_id": payload.mock_script_id,
    }
    if config is not None and config.provider_type != "mock":
        parameters = config.parameters if isinstance(config.parameters, dict) else {}
        snapshot["timeout_seconds"] = parameters.get("timeout_seconds", 60)
        snapshot["temperature"] = parameters.get("temperature")
        snapshot["max_output_tokens"] = parameters.get("max_output_tokens")
    now = datetime.now(UTC)
    task = AiTask(
        id=str(uuid.uuid4()),
        novel_id=novel.id,
        chapter_id=chapter.id if chapter is not None else None,
        task_type=payload.task_type,
        status=TaskStatus.QUEUED.value,
        model_config_id=config.id if config is not None else None,
        input_snapshot=snapshot,
        prompt_version=PROMPT_VERSION,
        output_text=None,
        error_code=None,
        error_message_safe=None,
        input_tokens=None,
        output_tokens=None,
        resolution=None,
        started_at=None,
        finished_at=None,
        created_at=now,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    cancel_event = threading.Event()
    with runtime.lock:
        runtime.cancel_events[task.id] = cancel_event
    runtime.executor.submit(
        run_ai_task,
        task.id,
        runtime.session_factory,
        runtime.broker,
        cancel_event,
    )
    logger.info("ai task queued", extra={"task_id": task.id})
    return _response(task)


def get_ai_task(session: Session, task_id: str) -> AiTaskResponse:
    return _response(_require(session, task_id))


def cancel_ai_task(session: Session, task_id: str, runtime: AiRuntime) -> AiTaskResponse:
    task = _require(session, task_id)
    try:
        transition(TaskStatus(task.status), TaskStatus.CANCELLED)
    except (ValueError, IllegalTaskTransition) as exc:
        raise TaskStateError("任务已经结束，不能再取消。") from exc
    with runtime.lock:
        event = runtime.cancel_events.get(task.id)
        if event is None:
            event = threading.Event()
            runtime.cancel_events[task.id] = event
    event.set()
    result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(AiTask)
            .where(
                AiTask.id == task.id,
                AiTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.RUNNING.value]),
            )
            .values(status=TaskStatus.CANCELLED.value, finished_at=datetime.now(UTC))
        ),
    )
    if result.rowcount != 1:
        session.rollback()
        raise TaskStateError("任务已经结束，不能再取消。")
    session.commit()
    session.expire_all()
    task = _require(session, task_id)
    runtime.broker.publish(
        task.id,
        "task.cancelled",
        {
            "task_id": task.id,
            "status": task.status,
            "provider_mode": _provider_mode(task),
        },
    )
    logger.info("ai task cancelled", extra={"task_id": task.id})
    return _response(task)


def accept_ai_task(
    session: Session,
    task_id: str,
    payload: AiTaskAccept,
) -> tuple[AiTaskResponse, ChapterResponse]:
    task = _require(session, task_id)
    if task.status != TaskStatus.COMPLETED.value:
        raise TaskStateError("只有生成完成的候选才能采纳。")
    if task.resolution is not None:
        raise TaskStateError("这份候选已经处理过。")
    if task.chapter_id is None:
        raise InvalidReference("这个任务没有关联章节，不能写入正文。")
    output = (task.output_text or "").strip()
    if output == "":
        raise TaskStateError("候选是空的，没有改写正文。")
    chapter = catalog_repo.get_chapter(session, task.chapter_id)
    if chapter is None:
        raise NotFound("章节不存在。")
    if chapter.revision != payload.target_revision:
        raise RevisionConflict()
    snapshot = task.input_snapshot if isinstance(task.input_snapshot, dict) else {}
    selection = snapshot.get("selection_text")
    selection_text = selection if isinstance(selection, str) else ""
    document = apply_candidate_text(
        chapter.content,
        output,
        mode=payload.apply_mode,
        selection_text=selection_text,
    )
    label = TASK_LABELS.get(task.task_type, task.task_type)
    task.resolution = "accepted"
    saved = apply_accepted_candidate(
        session,
        chapter.id,
        expected_revision=payload.target_revision,
        document=document,
        change_note=f"采纳{label}候选",
    )
    session.expire_all()
    task = _require(session, task_id)
    logger.info("ai candidate stored", extra={"task_id": task.id})
    return _response(task), ChapterResponse.model_validate(saved)


def reject_ai_task(session: Session, task_id: str) -> AiTaskResponse:
    task = _require(session, task_id)
    if task.status != TaskStatus.COMPLETED.value:
        raise TaskStateError("只有生成完成的候选才能放弃。")
    if task.resolution is not None:
        raise TaskStateError("这份候选已经处理过。")
    task.resolution = "rejected"
    session.commit()
    session.refresh(task)
    logger.info("ai candidate rejected", extra={"task_id": task.id})
    return _response(task)


def _resolve_model(session: Session, payload: AiTaskCreate) -> tuple[ModelConfig | None, str]:
    if payload.model_config_id:
        config = session.get(ModelConfig, payload.model_config_id)
        if config is None:
            raise NotFound("模型配置不存在。")
        if not config.is_enabled:
            raise ModelConfigInvalid("这个模型配置已停用。")
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟试运行不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return config, "mock"
        return config, "openai_compatible"
    if payload.use_mock:
        return None, "mock"
    config = session.scalars(
        select(ModelConfig)
        .where(
            ModelConfig.is_enabled.is_(True),
            ModelConfig.provider_type == "openai_compatible",
        )
        .order_by(ModelConfig.updated_at.desc(), ModelConfig.id.asc())
    ).first()
    if config is None:
        raise ModelNotConfigured()
    return config, "openai_compatible"


def _require(session: Session, task_id: str) -> AiTask:
    task = session.get(AiTask, task_id)
    if task is None:
        raise NotFound("任务不存在。")
    return task


def _provider_mode(task: AiTask) -> str:
    snapshot = task.input_snapshot if isinstance(task.input_snapshot, dict) else {}
    mode = snapshot.get("provider_mode")
    if mode == "mock":
        return "mock"
    return "openai_compatible"


def _response(task: AiTask) -> AiTaskResponse:
    snapshot = task.input_snapshot if isinstance(task.input_snapshot, dict) else {}
    model_name = snapshot.get("model_name")
    resolution = task.resolution if task.resolution in {"accepted", "rejected"} else None
    return AiTaskResponse(
        id=task.id,
        novel_id=task.novel_id,
        chapter_id=task.chapter_id,
        task_type=_task_type(task.task_type),
        status=_task_status(task.status),
        model_config_id=task.model_config_id,
        provider_mode="mock" if _provider_mode(task) == "mock" else "openai_compatible",
        model_name=model_name if isinstance(model_name, str) else "",
        prompt_version=task.prompt_version,
        output_text=task.output_text,
        error_code=task.error_code,
        error_message_safe=task.error_message_safe,
        input_tokens=task.input_tokens,
        output_tokens=task.output_tokens,
        resolution=cast("Literal['accepted', 'rejected'] | None", resolution),
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
    )


def _task_type(
    value: str,
) -> Literal["continue", "rewrite", "polish", "expand", "shrink", "proofread"]:
    if value in {"continue", "rewrite", "polish", "expand", "shrink", "proofread"}:
        return cast(
            "Literal['continue', 'rewrite', 'polish', 'expand', 'shrink', 'proofread']",
            value,
        )
    return "continue"


def _task_status(value: str) -> Literal["queued", "running", "completed", "failed", "cancelled"]:
    if value in {"queued", "running", "completed", "failed", "cancelled"}:
        return cast("Literal['queued', 'running', 'completed', 'failed', 'cancelled']", value)
    return "failed"
