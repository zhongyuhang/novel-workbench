"""Health endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.main import create_app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "ai-novel-writer",
        "version": "0.2.0",
        "database": "ok",
    }
    assert response.headers["x-request-id"]


def test_health_echoes_safe_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req-m0-health"})

    assert response.headers["x-request-id"] == "req-m0-health"
    assert response.json()["status"] == "ok"


def test_health_replaces_unsafe_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\r\nX-Evil: 1"})

    request_id = response.headers["x-request-id"]
    assert request_id != "bad id\r\nX-Evil: 1"
    assert "\n" not in request_id
    assert "\r" not in request_id


def test_health_reports_database_outage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_ping(session: object) -> None:
        del session
        raise OperationalError("SELECT 1", {}, Exception("disk offline"))

    monkeypatch.setattr("app.services.health.ping", fail_ping)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    assert error["message"] == "数据库暂时不可用。"
    assert error["request_id"]
    assert "disk offline" not in response.text


def test_development_starts_without_model_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "dev.db"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_AUTH_SECRET", "")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", "")
    get_settings.cache_clear()

    application = create_app()
    with TestClient(application) as test_client:
        response = test_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
