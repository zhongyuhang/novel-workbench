"""Model configuration use cases. Responses never include a plaintext API key."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.gateway import header_names
from app.ai.presets import load_provider_presets
from app.ai.provider import ModelEndpoint, ProviderError
from app.ai.registry import get_provider
from app.ai.ssrf import UnsafeModelUrl, assert_base_url_allowed
from app.core.errors import (
    DefaultModelProtected,
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
    ProviderPresetResponse,
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
    "MODEL_BASE_URL": 422,
    "MODEL_NOT_FOUND": 422,
}
_STORED_ERROR = {
    "MODEL_AUTH": "AUTH_FAILED",
    "MODEL_BASE_URL": "BASE_URL_INVALID",
    "MODEL_NOT_FOUND": "MODEL_NOT_FOUND",
    "MODEL_RATE_LIMIT": "RATE_LIMIT",
    "MODEL_UNAVAILABLE": "NETWORK",
    "MODEL_TIMEOUT": "TIMEOUT",
    "MODEL_BAD_RESPONSE": "INCOMPATIBLE_RESPONSE",
    "MODEL_BAD_REQUEST": "INCOMPATIBLE_RESPONSE",
}


def list_provider_presets() -> list[ProviderPresetResponse]:
    return [
        ProviderPresetResponse.model_validate(item.model_dump()) for item in load_provider_presets()
    ]


def list_model_configs(session: Session) -> list[ModelConfigResponse]:
    rows = session.scalars(
        select(ModelConfig).order_by(ModelConfig.updated_at.desc(), ModelConfig.id.asc())
    )
    return [_response(row) for row in rows]


def get_model_config(session: Session, config_id: str) -> ModelConfigResponse:
    return _response(_require(session, config_id))


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
        provider=payload.provider,
        provider_type=payload.provider_type,
        base_url=_normalize_base_url(payload.base_url, payload.provider_type),
        model_name=payload.model_name,
        secret_ref=_encrypt_optional(payload.api_key),
        encrypted_custom_headers=_encrypt_headers(payload.custom_headers),
        parameters=_parameters(payload),
        capabilities=_capabilities(payload.supports_streaming, payload.supports_json_output),
        is_enabled=payload.is_enabled,
        is_default=False,
        last_test_status="untested",
        last_tested_at=None,
        last_test_error_code=None,
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
    provider = row.provider if payload.provider is None else payload.provider
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
    if payload.clear_api_key:
        next_key = None
    elif payload.api_key is not None:
        next_key = _encrypt_optional(payload.api_key)
    next_headers = row.encrypted_custom_headers
    if payload.clear_custom_headers:
        next_headers = None
    elif payload.custom_headers is not None:
        next_headers = _encrypt_headers(payload.custom_headers)
    has_key = bool(next_key)
    _validate_endpoint(
        provider_type=provider_type,
        base_url=base_url,
        model_name=model_name,
        api_key=payload.api_key,
        require_key=(
            provider_type == "openai_compatible" and not has_key and not payload.clear_api_key
        ),
    )
    normalized_url = _normalize_base_url(base_url, provider_type)
    sensitive_changed = _sensitive_changed(
        row,
        provider=provider,
        provider_type=provider_type,
        base_url=normalized_url,
        model_name=model_name,
        secret_ref=next_key,
        encrypted_headers=next_headers,
        parameters=parameters,
    )
    row.provider = provider
    row.provider_type = provider_type
    row.base_url = normalized_url
    row.model_name = model_name
    row.secret_ref = next_key
    row.encrypted_custom_headers = next_headers
    row.parameters = parameters
    row.capabilities = capabilities
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.is_enabled is not None:
        row.is_enabled = payload.is_enabled
        if not payload.is_enabled:
            row.is_default = False
    if sensitive_changed:
        _invalidate_test(row)
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("model config updated")
    return _response(row)


def delete_model_config(session: Session, config_id: str) -> None:
    row = _require(session, config_id)
    if row.is_default:
        raise DefaultModelProtected()
    session.delete(row)
    session.commit()
    logger.info("model config deleted")


def set_default_model_config(session: Session, config_id: str) -> ModelConfigResponse:
    row = _require(session, config_id)
    if not row.is_enabled:
        raise ModelConfigInvalid("停用的配置不能设为默认。")
    if row.last_test_status != "success":
        raise ModelConfigInvalid("只有测试成功的配置可以设为默认。")
    session.execute(
        update(ModelConfig).where(ModelConfig.is_default.is_(True)).values(is_default=False)
    )
    session.flush()
    row.is_default = True
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("model config set as default")
    return _response(row)


def test_saved_model_config(session: Session, config_id: str) -> ModelTestResponse:
    row = _require(session, config_id)
    return _test_and_record(session, row)


def test_model_config(session: Session, payload: ModelTestRequest) -> ModelTestResponse:
    if payload.config_id:
        row = _require(session, payload.config_id)
        overrides = (
            payload.provider_type is not None
            or payload.base_url is not None
            or payload.model_name is not None
            or payload.api_key is not None
            or payload.timeout_seconds is not None
        )
        if not overrides:
            return _test_and_record(session, row)
        provider_type = payload.provider_type or row.provider_type
        base_url = payload.base_url if payload.base_url is not None else row.base_url
        model_name = payload.model_name or row.model_name
        parameters = _as_dict(row.parameters)
        capabilities = _as_dict(row.capabilities)
        api_key = (
            payload.api_key if payload.api_key is not None else _decrypt_stored(row.secret_ref)
        )
        stored_headers = _stored_header_values(row)
    else:
        provider_type = payload.provider_type or "openai_compatible"
        base_url = payload.base_url or ""
        model_name = payload.model_name or ""
        parameters = {"timeout_seconds": payload.timeout_seconds or 30, "max_retries": 0}
        capabilities = {"supports_streaming": False}
        api_key = payload.api_key or ""
        stored_headers = {}
    if payload.timeout_seconds is not None:
        parameters = {**parameters, "timeout_seconds": payload.timeout_seconds}
    parameters = {**parameters, "max_retries": 0}
    started = time.perf_counter()
    try:
        _run_connection_test(
            provider_type=provider_type,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            parameters=parameters,
            capabilities=capabilities,
            extra_headers=stored_headers,
        )
    except ProviderRequestFailed:
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return _success_response(provider_type, model_name, elapsed_ms)


def _test_and_record(session: Session, row: ModelConfig) -> ModelTestResponse:
    parameters = {**_as_dict(row.parameters), "max_retries": 0}
    started = time.perf_counter()
    try:
        _run_connection_test(
            provider_type=row.provider_type,
            base_url=row.base_url,
            model_name=row.model_name,
            api_key=_decrypt_stored(row.secret_ref) if row.provider_type != "mock" else "",
            parameters=parameters,
            capabilities=_as_dict(row.capabilities),
            extra_headers=_stored_header_values(row),
        )
    except ProviderRequestFailed as exc:
        _record_failure(row, exc.code, exc.message)
        session.commit()
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    row.last_test_status = "success"
    row.last_tested_at = _now()
    row.last_test_error_code = None
    row.updated_at = row.last_tested_at
    session.commit()
    logger.info("model config tested")
    return _success_response(row.provider_type, row.model_name, elapsed_ms)


def _run_connection_test(
    *,
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str,
    parameters: dict[str, object],
    capabilities: dict[str, object],
    extra_headers: dict[str, str],
) -> None:
    normalized = _normalize_base_url(base_url, provider_type)
    if provider_type == "openai_compatible":
        try:
            assert_base_url_allowed(normalized)
        except UnsafeModelUrl as exc:
            raise ProviderRequestFailed("MODEL_BASE_URL", exc.message, 422) from exc
    endpoint = _endpoint(
        provider_type=provider_type,
        base_url=normalized,
        model_name=model_name,
        api_key=api_key,
        parameters=parameters,
        capabilities=capabilities,
        extra_headers=extra_headers,
    )
    provider = get_provider(endpoint)
    try:
        provider.validate_config(endpoint)
        provider.test_connection(endpoint)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc


def _success_response(provider_type: str, model_name: str, elapsed_ms: int) -> ModelTestResponse:
    mode: Literal["openai_compatible", "mock"]
    if provider_type == "mock":
        message = "模拟模型可用。当前没有连接外部服务。"
        mode = "mock"
    else:
        message = f"连接成功。模型 {model_name}，耗时 {elapsed_ms} 毫秒。"
        mode = "openai_compatible"
    return ModelTestResponse(
        ok=True,
        provider_mode=mode,
        message=message,
        model_name=model_name,
        elapsed_ms=elapsed_ms,
        error_code=None,
    )


def _record_failure(row: ModelConfig, provider_code: str, message: str) -> None:
    row.last_test_status = "failed"
    row.last_tested_at = _now()
    row.last_test_error_code = _classify(provider_code, message)
    row.is_default = False
    row.updated_at = row.last_tested_at


def _classify(provider_code: str, message: str) -> str:
    if provider_code == "MODEL_CONFIG_INVALID":
        if "API Key" in message or "密钥" in message:
            return "KEY_MISSING"
        return "BASE_URL_INVALID"
    return _STORED_ERROR.get(provider_code, "INCOMPATIBLE_RESPONSE")


def _response(row: ModelConfig) -> ModelConfigResponse:
    hint, configured = _hint(row.secret_ref)
    names, headers_configured = header_names(row.encrypted_custom_headers)
    provider_type: Literal["openai_compatible", "mock"] = (
        "mock" if row.provider_type == "mock" else "openai_compatible"
    )
    status = (
        row.last_test_status
        if row.last_test_status
        in {
            "untested",
            "success",
            "failed",
            "stale",
        }
        else "untested"
    )
    return ModelConfigResponse(
        id=row.id,
        display_name=row.display_name,
        provider=row.provider or "custom",
        provider_type=provider_type,
        base_url=row.base_url,
        model_name=row.model_name,
        api_key_configured=configured,
        api_key_hint=hint,
        custom_headers_configured=headers_configured,
        custom_header_names=names,
        parameters=_as_dict(row.parameters),
        capabilities=_as_dict(row.capabilities),
        is_enabled=row.is_enabled,
        is_default=row.is_default,
        last_test_status=status,  # type: ignore[arg-type]
        last_tested_at=row.last_tested_at,
        last_test_error_code=row.last_test_error_code,
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


def _encrypt_headers(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    try:
        return encrypt_api_key(json.dumps(headers, ensure_ascii=False, sort_keys=True))
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc


def _decrypt_stored(secret_ref: str | None) -> str:
    if not secret_ref:
        return ""
    try:
        return decrypt_api_key(secret_ref)
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc


def _stored_header_values(row: ModelConfig) -> dict[str, str]:
    if not row.encrypted_custom_headers:
        return {}
    try:
        raw = decrypt_api_key(row.encrypted_custom_headers)
        parsed = json.loads(raw)
    except (SecretStorageError, ValueError) as exc:
        raise SecretStorageUnavailable() from exc
    if not isinstance(parsed, dict):
        raise SecretStorageUnavailable()
    return {str(key): str(value) for key, value in parsed.items() if isinstance(value, str)}


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
        try:
            assert_base_url_allowed(base_url)
        except UnsafeModelUrl as exc:
            raise ModelConfigInvalid(exc.message) from exc
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


def _sensitive_changed(
    row: ModelConfig,
    *,
    provider: str,
    provider_type: str,
    base_url: str,
    model_name: str,
    secret_ref: str | None,
    encrypted_headers: str | None,
    parameters: dict[str, object],
) -> bool:
    current = _as_dict(row.parameters)
    watched = ("timeout_seconds", "temperature", "max_output_tokens")
    parameter_changed = any(current.get(key) != parameters.get(key) for key in watched)
    return bool(
        provider != row.provider
        or provider_type != row.provider_type
        or base_url != row.base_url
        or model_name != row.model_name
        or secret_ref != row.secret_ref
        or encrypted_headers != row.encrypted_custom_headers
        or parameter_changed
    )


def _invalidate_test(row: ModelConfig) -> None:
    if row.last_test_status == "untested":
        return
    row.last_test_status = "stale"
    row.last_test_error_code = "CONFIG_CHANGED"
    row.is_default = False


def _endpoint(
    *,
    provider_type: str,
    base_url: str,
    model_name: str,
    api_key: str,
    parameters: dict[str, object],
    capabilities: dict[str, object],
    extra_headers: dict[str, str],
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
        extra_headers=extra_headers,
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
