"""Resolve a stored model config and build one outbound endpoint.

Business modules call this instead of decrypting keys or picking a vendor.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ModelEndpoint
from app.ai.ssrf import UnsafeModelUrl, assert_base_url_allowed
from app.core.errors import ModelConfigInvalid, NotFound, SecretStorageUnavailable
from app.core.secrets import SecretStorageError, decrypt_api_key
from app.models.ai import ModelConfig


def load_enabled_config(session: Session, config_id: str) -> ModelConfig:
    config = session.get(ModelConfig, config_id)
    if config is None:
        raise NotFound("模型配置不存在。")
    if not config.is_enabled:
        raise ModelConfigInvalid("这个模型配置已停用。")
    return config


def enabled_default(session: Session) -> ModelConfig | None:
    return session.scalars(
        select(ModelConfig).where(
            ModelConfig.is_enabled.is_(True),
            ModelConfig.is_default.is_(True),
        )
    ).first()


def latest_enabled(session: Session, provider_type: str) -> ModelConfig | None:
    return session.scalars(
        select(ModelConfig)
        .where(
            ModelConfig.is_enabled.is_(True),
            ModelConfig.provider_type == provider_type,
        )
        .order_by(ModelConfig.updated_at.desc(), ModelConfig.id.asc())
    ).first()


def endpoint_from_config(config: ModelConfig) -> ModelEndpoint:
    """Decrypt the stored key and headers. Raises before any outbound call."""

    parameters = _as_dict(config.parameters)
    capabilities = _as_dict(config.capabilities)
    if config.provider_type == "mock":
        return ModelEndpoint(
            base_url=config.base_url or "mock://local",
            model_name=config.model_name,
            api_key="",
            timeout_seconds=_float(parameters.get("timeout_seconds"), 30),
            supports_streaming=capabilities.get("supports_streaming") is not False,
            provider_type="mock",
            max_retries=0,
            temperature=_optional_float(parameters.get("temperature")),
            max_output_tokens=_optional_int(parameters.get("max_output_tokens")),
            parameters=parameters,
        )
    if config.provider_type != "openai_compatible":
        raise ModelConfigInvalid("不支持的模型服务类型。")
    try:
        assert_base_url_allowed(config.base_url)
    except UnsafeModelUrl as exc:
        raise ModelConfigInvalid(exc.message) from exc
    if not config.secret_ref:
        raise ModelConfigInvalid("这个模型还没有可用的 API Key。")
    try:
        api_key = decrypt_api_key(str(config.secret_ref))
        headers = _decrypt_headers(config.encrypted_custom_headers)
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc
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
        extra_headers=headers,
    )


def _decrypt_headers(ciphertext: str | None) -> dict[str, str]:
    if not ciphertext:
        return {}
    raw = decrypt_api_key(ciphertext)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SecretStorageError("Stored custom headers could not be decrypted.")
    headers: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str):
            headers[key] = value
    return headers


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


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


def header_names(ciphertext: str | None) -> tuple[list[str], bool]:
    if not ciphertext:
        return [], False
    try:
        names = sorted(_decrypt_headers(ciphertext))
    except (SecretStorageError, ValueError):
        return [], True
    return names, True
