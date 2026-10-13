"""Model API key encryption and log redaction."""

import logging

import pytest
from cryptography.fernet import Fernet

from app.ai.provider import ModelEndpoint
from app.core.logging import JsonFormatter, RequestContextFilter
from app.core.redaction import redact_text
from app.core.secrets import (
    SecretStorageError,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)

PLAINTEXT = "sk-test-secret-value-should-not-leak"


def test_encrypt_roundtrip_hides_plaintext() -> None:
    master_key = Fernet.generate_key().decode()

    ciphertext = encrypt_api_key(PLAINTEXT, master_key=master_key)

    assert PLAINTEXT not in ciphertext
    assert decrypt_api_key(ciphertext, master_key=master_key) == PLAINTEXT


def test_missing_or_placeholder_master_key_is_rejected() -> None:
    with pytest.raises(SecretStorageError):
        encrypt_api_key(PLAINTEXT, master_key="")
    with pytest.raises(SecretStorageError):
        encrypt_api_key(PLAINTEXT, master_key="replace-with-a-fernet-key")


def test_invalid_ciphertext_is_rejected() -> None:
    master_key = Fernet.generate_key().decode()

    with pytest.raises(SecretStorageError):
        decrypt_api_key("not-a-token", master_key=master_key)


def test_mask_does_not_return_the_full_key() -> None:
    masked = mask_api_key(PLAINTEXT)

    assert masked == "••••leak"
    assert masked != PLAINTEXT
    assert PLAINTEXT[:-4] not in masked
    assert mask_api_key("short") == "configured"


def test_endpoint_repr_masks_api_key() -> None:
    endpoint = ModelEndpoint(
        base_url="https://example.invalid/v1",
        model_name="demo-model",
        api_key=PLAINTEXT,
        timeout_seconds=30,
        supports_streaming=True,
    )

    rendered = repr(endpoint)

    assert PLAINTEXT not in rendered
    assert "••••leak" in rendered


def test_redact_text_removes_bearer_and_api_keys() -> None:
    raw = "Authorization: Bearer sk-supersecretvalue api_key=sk-supersecretvalue"

    redacted = redact_text(raw)

    assert "sk-supersecretvalue" not in redacted
    assert "[REDACTED]" in redacted


def test_json_log_formatter_redacts_message() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider rejected api_key=sk-supersecretvalue",
        args=(),
        exc_info=None,
    )
    RequestContextFilter().filter(record)

    formatted = JsonFormatter().format(record)

    assert "sk-supersecretvalue" not in formatted
    assert "[REDACTED]" in formatted
