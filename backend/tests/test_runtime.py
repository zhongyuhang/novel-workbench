"""Production configuration refuses open and placeholder secrets."""

import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.main import create_app


def test_production_rejects_placeholder_auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_AUTH_SECRET", "replace-with-a-long-random-secret")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", "replace-with-a-fernet-key")
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:43117")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="APP_AUTH_SECRET"):
        create_app()


def test_production_rejects_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "local-access-password")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CORS_ORIGINS", "*")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app()


def test_cors_reflects_only_configured_origin(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    allowed = client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:43117"})
    blocked = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:43117"
    assert "access-control-allow-origin" not in blocked.headers
