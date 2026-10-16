"""Model configuration use cases. Responses never include a plaintext API key."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ModelEndpoint, ProviderError
from app.ai.registry import get_provider
from app.core.errors import (
    ModelConfigInvalid,
    NotFound,
    ProviderRequestFailed,
    SecretStorageUnavailable,
)
from app.core.secrets import SecretStorageError, decrypt_api_key, encrypt_api_key, mask_api_key
from app.models.ai import ModelConfig
from app.schemas.ai import (
    ModelConfigPatch,
    ModelConfigResponse,
    ModelConfigWrite,
    ModelTestRequest,
    ModelTestResponse,
)

logger = logging.getLogger("app.models")

_STATUS = {
    "MODEL_TIMEOUT": 504,
    "MODEL_UNAVAILABLE": 503,
    "MODEL_RATE_LIMIT": 429,
    "MODEL_AUTH": 502,
    "MODEL_BAD_REQUEST": 422,
    "MODEL_BAD_RESPONSE": 502,
    "MODEL_CONFIG_INVALID": 422,
}


def list_model_configs(session: Session) -> list[ModelConfigResponse]:
    rows = session.scalars(
        select(ModelConfig).order_by(ModelConfig.updated_at.desc(), ModelConfig.id.asc())
    )
    return [_response(row) for row in rows]


def create_model_config(session: Session, payload: ModelConfigWrite) -> ModelConfigResponse:
    _validate_endpoint(
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        model_name=payload.model_name,
        api_key=payload.api_key,
        require_key=payload.provider_type == "openai_compatible",
    )
    now = _now()
    row = ModelConfig(
        id=str(uuid.uuid4()),
        display_name=payload.display_name,
        provider_type=payload.provider_type,
        base_url=_normalize_base_url(payload.base_url, payload.provider_type),
        model_name=payload.model_name,
        secret_ref=_encrypt_optional(payload.api_key),
        parameters=_parameters(payload),
        capabilities=_capabilities(payload.supports_streaming, payload.supports_json_output),
        is_enabled=payload.is_enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("model config created")
    return _response(row)


def update_model_config(
    session: Session,
    config_id: str,
    payload: ModelConfigPatch,
) -> ModelConfigResponse:
    row = _require(session, config_id)
    provider_type = payload.provider_type or row.provider_type
    base_url = row.base_url if payload.base_url is None else payload.base_url
    model_name = row.model_name if payload.model_name is None else payload.model_name
    parameters = _as_dict(row.parameters)
    capabilities = _as_dict(row.capabilities)
    if payload.timeout_seconds is not None:
        parameters["timeout_seconds"] = payload.timeout_seconds
    if payload.max_retries is not None:
        parameters["max_retries"] = payload.max_retries
    if payload.temperature is not None:
        parameters["temperature"] = payload.temperature
    if payload.max_output_tokens is not None:
        parameters["max_output_tokens"] = payload.max_output_tokens
    if payload.supports_streaming is not None:
        capabilities["supports_streaming"] = payload.supports_streaming
    if payload.supports_json_output is not None:
        capabilities["supports_json_output"] = payload.supports_json_output
    next_key = row.secret_ref
    if payload.api_key is not None:
        next_key = _encrypt_optional(payload.api_key)
    has_key = bool(next_key)
    _validate_endpoint(
        provider_type=provider_type,
        base_url=base_url,
        model_name=model_name,
        api_key=payload.api_key,
        require_key=provider_type == "openai_compatible" and not has_key,
    )
    row.provider_type = provider_type
    row.base_url = _normalize_base_url(base_url, provider_type)
    row.model_name = model_name
    row.secret_ref = next_key
    row.parameters = parameters
    row.capabilities = capabilities
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.is_enabled is not None:
        row.is_enabled = payload.is_enabled
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("model config updated")
    return _response(row)


def delete_model_config(session: Session, config_id: str) -> None:
    row = _require(session, config_id)
    session.delete(row)
    session.commit()
    logger.info("model config deleted")


def test_model_config(session: Session, payload: ModelTestRequest) -> ModelTestResponse:
    if payload.config_id:
        row = _require(session, payload.config_id)
        provider_type = payload.provider_type or row.provider_type
        base_url = payload.base_url if payload.base_url is not None else row.base_url
        model_name = payload.model_name or row.model_name
        parameters = _as_dict(row.parameters)
        capabilities = _as_dict(row.capabilities)
        if payload.api_key is not None:
            api_key = payload.api_key
        else:
            api_key = _decrypt_stored(row.secret_ref)
    else:
        provider_type = payload.provider_type or "openai_compatible"
        base_url = payload.base_url or ""
        model_name = payload.model_name or ""
        parameters = {"timeout_seconds": payload.timeout_seconds or 30, "max_retries": 0}
        capabilities = {"supports_streaming": False}
        api_key = payload.api_key or ""
    if payload.timeout_seconds is not None:
        parameters = {**parameters, "timeout_seconds": payload.timeout_seconds}
    parameters = {**parameters, "max_retries": 0}
    endpoint = _endpoint(
        provider_type=provider_type,
        base_url=_normalize_base_url(base_url, provider_type),
        model_name=model_name,
        api_key=api_key,
        parameters=parameters,
        capabilities=capabilities,
    )
    provider = get_provider(endpoint)
    try:
        provider.validate_config(endpoint)
        provider.test_connection(endpoint)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    mode: Literal["openai_compatible", "mock"]
    if endpoint.provider_type == "mock":
        message = "模拟模型可用。当前没有连接外部服务。"
        mode = "mock"
    else:
        message = "连接成功。"
        mode = "openai_compatible"
    logger.info("model config tested")
    return ModelTestResponse(ok=True, provider_mode=mode, message=message)


def _response(row: ModelConfig) -> ModelConfigResponse:
    hint, configured = _hint(row.secret_ref)
    provider_type: Literal["openai_compatible", "mock"] = (
        "mock" if row.provider_type == "mock" else "openai_compatible"
    )
    return ModelConfigResponse(
        id=row.id,
        display_name=row.display_name,
        provider_type=provider_type,
        base_url=row.base_url,
        model_name=row.model_name,
        api_key_configured=configured,
        api_key_hint=hint,
        parameters=_as_dict(row.parameters),
        capabilities=_as_dict(row.capabilities),
        is_enabled=row.is_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _hint(secret_ref: str | None) -> tuple[str | None, bool]:
    if not secret_ref:
        return None, False
    try:
        plaintext = decrypt_api_key(secret_ref)
    except SecretStorageError:
        logger.warning("stored model key could not be decrypted")
        return None, True
    masked = mask_api_key(plaintext)
    return (masked or None), True


def _encrypt_optional(api_key: str | None) -> str | None:
    if api_key is None:
        return None
    try:
        return encrypt_api_key(api_key)
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc


def _decrypt_stored(secret_ref: str | None) -> str:
    if not secret_ref:
        return ""
    try:
        return decrypt_api_key(secret_ref)
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc


def _validate_endpoint(
    *,
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str | None,
    require_key: bool,
) -> None:
    if model_name.strip() == "":
        raise ModelConfigInvalid("请填写模型名称。")
    if provider_type == "openai_compatible":
        if urlsplit(base_url).scheme not in {"http", "https"} or urlsplit(base_url).netloc == "":
            raise ModelConfigInvalid("Base URL 需要以 http:// 或 https:// 开头。")
        if require_key and not api_key:
            raise ModelConfigInvalid("请填写 API Key。")
        return
    if provider_type != "mock":
        raise ModelConfigInvalid("不支持的模型服务类型。")


def _normalize_base_url(base_url: str, provider_type: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if provider_type == "mock":
        return cleaned or "mock://local"
    return cleaned


def _parameters(payload: ModelConfigWrite) -> dict[str, object]:
    data: dict[str, object] = {
        "timeout_seconds": payload.timeout_seconds,
        "max_retries": payload.max_retries,
        "max_output_tokens": payload.max_output_tokens,
    }
    if payload.temperature is not None:
        data["temperature"] = payload.temperature
    return data


def _capabilities(streaming: bool, json_output: bool) -> dict[str, object]:
    return {"supports_streaming": streaming, "supports_json_output": json_output}


def _endpoint(
    *,
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str,
    parameters: dict[str, object],
    capabilities: dict[str, object],
) -> ModelEndpoint:
    return ModelEndpoint(
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        timeout_seconds=_float(parameters.get("timeout_seconds"), 30),
        supports_streaming=bool(capabilities.get("supports_streaming")),
        provider_type=provider_type,
        max_retries=_int(parameters.get("max_retries"), 0),
        temperature=_optional_float(parameters.get("temperature")),
        max_output_tokens=_optional_int(parameters.get("max_output_tokens")),
        parameters=parameters,
    )


def _public_provider_error(exc: ProviderError) -> ProviderRequestFailed:
    status = _STATUS.get(exc.code, 502)
    return ProviderRequestFailed(exc.code, exc.safe_message, status)


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _require(session: Session, config_id: str) -> ModelConfig:
    row = session.get(ModelConfig, config_id)
    if row is None:
        raise NotFound("模型配置不存在。")
    return row


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
