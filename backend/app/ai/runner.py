"""Background execution. A finished task is a candidate; the chapter is not modified."""

import logging
import threading
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.ai.broker import TaskBroker
from app.ai.prompts import PROMPT_VERSION
from app.ai.provider import GenerationRequest, ModelEndpoint, ModelProvider, ProviderError
from app.ai.registry import get_provider
from app.ai.tasks import IllegalTaskTransition, TaskStatus, transition
from app.core.secrets import SecretStorageError, decrypt_api_key
from app.models.ai import AiTask, ModelConfig

logger = logging.getLogger("app.ai.runner")


def run_ai_task(
    task_id: str,
    session_factory: sessionmaker[Session],
    broker: TaskBroker,
    cancel_event: threading.Event,
) -> None:
    try:
        _execute(task_id, session_factory, broker, cancel_event)
    except Exception as exc:
        logger.warning(
            "ai task crashed",
            extra={"task_id": task_id, "error_type": type(exc).__name__},
        )
        _fail_if_open(
            session_factory,
            broker,
            task_id,
            "INTERNAL_ERROR",
            "生成没有完成。正文没有被修改。",
        )


def _execute(
    task_id: str,
    session_factory: sessionmaker[Session],
    broker: TaskBroker,
    cancel_event: threading.Event,
) -> None:
    session = session_factory()
    prepared: tuple[ModelProvider, GenerationRequest] | None = None
    try:
        task = session.get(AiTask, task_id)
        if task is None:
            return
        if task.status != TaskStatus.QUEUED:
            if task.status == TaskStatus.CANCELLED:
                _publish_status(broker, task, "task.cancelled")
            return
        if cancel_event.is_set():
            _mark(session, task_id, TaskStatus.QUEUED, TaskStatus.CANCELLED, finished_at=_now())
            session.commit()
            task = _require(session, task_id)
            _publish_status(broker, task, "task.cancelled")
            return
        snapshot = _snapshot(task)
        prompt = snapshot.get("prompt")
        if not isinstance(prompt, str) or prompt.strip() == "":
            _mark(
                session,
                task_id,
                TaskStatus.QUEUED,
                TaskStatus.FAILED,
                error_code="MODEL_CONFIG_INVALID",
                error_message_safe="任务缺少可执行的提示，已停止。正文没有被修改。",
                finished_at=_now(),
            )
            session.commit()
            task = _require(session, task_id)
            _publish_status(broker, task, "task.failed")
            return
        try:
            endpoint = _endpoint(session, task, snapshot)
            provider = get_provider(endpoint)
            provider.validate_config(endpoint)
        except (ProviderError, SecretStorageError) as exc:
            code, message = _safe_failure(exc)
            _mark(
                session,
                task_id,
                TaskStatus.QUEUED,
                TaskStatus.FAILED,
                error_code=code,
                error_message_safe=message,
                finished_at=_now(),
            )
            session.commit()
            task = _require(session, task_id)
            _publish_status(broker, task, "task.failed")
            return
        usage = provider.estimate_usage(
            GenerationRequest(
                endpoint=endpoint,
                prompt=prompt,
                max_output_tokens=endpoint.max_output_tokens,
            )
        )
        started = _mark(
            session,
            task_id,
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            started_at=_now(),
            input_tokens=usage.input_tokens,
            prompt_version=PROMPT_VERSION,
        )
        if not started:
            session.rollback()
            current = session.get(AiTask, task_id)
            if current is not None and current.status == TaskStatus.CANCELLED:
                _publish_status(broker, current, "task.cancelled")
            return
        session.commit()
        task = _require(session, task_id)
        _publish_status(broker, task, "task.started")
        request = GenerationRequest(
            endpoint=endpoint,
            prompt=prompt,
            max_output_tokens=endpoint.max_output_tokens,
        )
        prepared = (provider, request)
    finally:
        session.close()

    if prepared is None:
        return
    provider, request = prepared

    pieces: list[str] = []
    dropping = False
    try:
        for event in provider.stream(request):
            cancelled = cancel_event.is_set() or not _is_running(session_factory, task_id)
            if not dropping and cancelled:
                dropping = True
                _cancel_open(session_factory, broker, task_id)
            if dropping or event.event != "token" or event.data == "":
                continue
            pieces.append(event.data)
            if not _write_output(session_factory, task_id, "".join(pieces), len(pieces)):
                dropping = True
                _cancel_open(session_factory, broker, task_id)
                continue
            broker.publish(
                task_id,
                "token",
                {"task_id": task_id, "index": len(pieces) - 1, "text": event.data},
            )
    except ProviderError as exc:
        _fail_if_open(session_factory, broker, task_id, exc.code, exc.safe_message)
        return
    except Exception as exc:
        logger.warning(
            "ai provider crashed",
            extra={"task_id": task_id, "error_type": type(exc).__name__},
        )
        _fail_if_open(
            session_factory,
            broker,
            task_id,
            "MODEL_UNAVAILABLE",
            "模型请求失败。正文没有被修改。",
        )
        return

    text = "".join(pieces).strip()
    if cancel_event.is_set() or not _is_running(session_factory, task_id):
        _cancel_open(session_factory, broker, task_id)
        return
    if text == "":
        _fail_if_open(
            session_factory,
            broker,
            task_id,
            "EMPTY_OUTPUT",
            "模型没有返回可用文本。正文没有被修改。",
        )
        return
    session = session_factory()
    try:
        updated = _mark(
            session,
            task_id,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
            output_text=text,
            output_tokens=len(pieces),
            finished_at=_now(),
            error_code=None,
            error_message_safe=None,
        )
        if not updated:
            session.rollback()
            return
        session.commit()
        task = _require(session, task_id)
        _publish_status(broker, task, "task.completed")
    finally:
        session.close()


def _endpoint(session: Session, task: AiTask, snapshot: dict[str, object]) -> ModelEndpoint:
    mode = snapshot.get("provider_mode")
    if mode == "mock":
        return ModelEndpoint(
            base_url="mock://local",
            model_name=_text(snapshot.get("model_name"), "mock"),
            api_key="",
            timeout_seconds=_float(snapshot.get("timeout_seconds"), 30),
            supports_streaming=True,
            provider_type="mock",
            max_retries=0,
            temperature=_optional_float(snapshot.get("temperature")),
            max_output_tokens=_optional_int(snapshot.get("max_output_tokens")),
            parameters={
                "mock_behavior": _text(snapshot.get("mock_behavior"), "stream"),
                "mock_tokens": snapshot.get("mock_tokens"),
                "mock_script_id": snapshot.get("mock_script_id"),
            },
        )
    config = session.get(ModelConfig, task.model_config_id) if task.model_config_id else None
    if config is None or not config.is_enabled:
        raise ProviderError("MODEL_NOT_CONFIGURED", "模型配置已经不可用。正文没有被修改。")
    if config.provider_type == "mock":
        raise ProviderError("MODEL_CONFIG_INVALID", "模拟模型配置和任务记录不一致。")
    if not config.secret_ref:
        raise ProviderError("MODEL_CONFIG_INVALID", "这个模型还没有可用的 API Key。")
    try:
        api_key = decrypt_api_key(config.secret_ref)
    except SecretStorageError as exc:
        raise ProviderError(
            "SECRET_STORAGE_UNAVAILABLE",
            "服务器无法解密模型密钥。请检查加密主密钥后重新保存配置。",
        ) from exc
    parameters = config.parameters if isinstance(config.parameters, dict) else {}
    capabilities = config.capabilities if isinstance(config.capabilities, dict) else {}
    return ModelEndpoint(
        base_url=config.base_url,
        model_name=config.model_name,
        api_key=api_key,
        timeout_seconds=_float(parameters.get("timeout_seconds"), 60),
        supports_streaming=capabilities.get("supports_streaming") is not False,
        provider_type="openai_compatible",
        max_retries=_int(parameters.get("max_retries"), 2),
        temperature=_optional_float(parameters.get("temperature")),
        max_output_tokens=_optional_int(parameters.get("max_output_tokens")),
        parameters=parameters,
    )


def _mark(
    session: Session,
    task_id: str,
    current: TaskStatus,
    target: TaskStatus,
    **values: object,
) -> bool:
    task = session.get(AiTask, task_id)
    if task is None:
        return False
    try:
        transition(TaskStatus(task.status), target)
    except (ValueError, IllegalTaskTransition):
        return False
    if task.status != current.value:
        return False
    result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(AiTask)
            .where(AiTask.id == task_id, AiTask.status == current.value)
            .values(status=target.value, **values)
        ),
    )
    return result.rowcount == 1


def _write_output(
    session_factory: sessionmaker[Session],
    task_id: str,
    output_text: str,
    output_tokens: int,
) -> bool:
    session = session_factory()
    try:
        result = cast(
            CursorResult[tuple[object, ...]],
            session.execute(
                update(AiTask)
                .where(AiTask.id == task_id, AiTask.status == TaskStatus.RUNNING.value)
                .values(output_text=output_text, output_tokens=output_tokens)
            ),
        )
        if result.rowcount != 1:
            session.rollback()
            return False
        session.commit()
        return True
    finally:
        session.close()


def _is_running(session_factory: sessionmaker[Session], task_id: str) -> bool:
    session = session_factory()
    try:
        status = session.execute(
            select(AiTask.status).where(AiTask.id == task_id)
        ).scalar_one_or_none()
        session.rollback()
        return status == TaskStatus.RUNNING.value
    finally:
        session.close()


def _cancel_open(
    session_factory: sessionmaker[Session],
    broker: TaskBroker,
    task_id: str,
) -> None:
    session = session_factory()
    try:
        changed = _mark(
            session,
            task_id,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            finished_at=_now(),
        )
        if not changed:
            changed = _mark(
                session,
                task_id,
                TaskStatus.QUEUED,
                TaskStatus.CANCELLED,
                finished_at=_now(),
            )
        session.commit()
        task = session.get(AiTask, task_id)
        if task is not None and task.status == TaskStatus.CANCELLED:
            _publish_status(broker, task, "task.cancelled")
        del changed
    finally:
        session.close()


def _fail_if_open(
    session_factory: sessionmaker[Session],
    broker: TaskBroker,
    task_id: str,
    code: str,
    message: str,
) -> None:
    session = session_factory()
    try:
        changed = False
        for current in (TaskStatus.RUNNING, TaskStatus.QUEUED):
            changed = _mark(
                session,
                task_id,
                current,
                TaskStatus.FAILED,
                error_code=code,
                error_message_safe=message,
                finished_at=_now(),
            )
            if changed:
                break
        if not changed:
            session.rollback()
            return
        session.commit()
        task = session.get(AiTask, task_id)
        if task is not None:
            _publish_status(broker, task, "task.failed")
    finally:
        session.close()


def _publish_status(broker: TaskBroker, task: AiTask, event: str) -> None:
    snapshot = _snapshot(task)
    data: dict[str, object] = {
        "task_id": task.id,
        "status": task.status,
        "provider_mode": _text(snapshot.get("provider_mode"), "openai_compatible"),
    }
    if event == "task.completed":
        data["output_text"] = task.output_text or ""
    if event == "task.failed":
        data["error_code"] = task.error_code or "MODEL_UNAVAILABLE"
        data["error_message"] = task.error_message_safe or "生成没有完成。正文没有被修改。"
    broker.publish(task.id, event, data)


def _snapshot(task: AiTask) -> dict[str, object]:
    raw = task.input_snapshot
    if isinstance(raw, dict):
        return raw
    return {}


def _require(session: Session, task_id: str) -> AiTask:
    task = session.get(AiTask, task_id)
    if task is None:
        raise RuntimeError("AI task disappeared before it could be updated.")
    return task


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ProviderError):
        return exc.code, exc.safe_message
    if isinstance(exc, SecretStorageError):
        return (
            "SECRET_STORAGE_UNAVAILABLE",
            "服务器无法解密模型密钥。请检查加密主密钥后重新保存配置。",
        )
    return "MODEL_UNAVAILABLE", "模型请求失败。正文没有被修改。"


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _float(value: object, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


def _int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _now() -> datetime:
    return datetime.now(UTC)
