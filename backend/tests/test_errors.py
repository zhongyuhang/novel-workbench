"""Error envelope."""

import json

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.errors import http_exception_handler, validation_exception_handler
from app.core.logging import request_id_var


def test_unknown_path_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/missing", headers={"X-Request-ID": "req-missing"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "请求的资源不存在。",
            "request_id": "req-missing",
        }
    }
    assert response.headers["x-request-id"] == "req-missing"


def test_internal_error_hides_path_and_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(session: object, *, version: str) -> None:
        del session, version
        raise RuntimeError("failed at /tmp/secret.db with sk-supersecretvalue")

    monkeypatch.setattr("app.api.v1.health.check_health", explode)
    # Starlette reports handled server errors and then re-raises them.
    with TestClient(client.app, raise_server_exceptions=False) as quiet:
        response = quiet.get("/api/v1/health", headers={"X-Request-ID": "req-boom"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "服务器内部错误。"
    assert body["error"]["request_id"] == "req-boom"
    assert response.headers["x-request-id"] == "req-boom"
    assert "sk-supersecretvalue" not in response.text
    assert "/tmp/secret.db" not in response.text


def test_validation_handler_drops_input_echo() -> None:
    request_id_var.set("req-validation")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/health",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    exc = RequestValidationError(
        [
            {
                "loc": ("body", "api_key"),
                "msg": "field required",
                "type": "missing",
                "input": "sk-supersecretvalue",
            }
        ]
    )

    response = validation_exception_handler(request, exc)
    encoded = bytes(response.body).decode()

    assert response.status_code == 422
    assert json.loads(encoded)["error"]["code"] == "VALIDATION_ERROR"
    assert "sk-supersecretvalue" not in encoded
    request_id_var.set(None)


def test_http_handler_keeps_safe_chinese_detail() -> None:
    request_id_var.set("req-auth")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/private",
        "headers": [],
        "query_string": b"",
    }
    response = http_exception_handler(
        Request(scope),
        HTTPException(status_code=401, detail="登录状态无效或已过期。"),
    )

    assert response.status_code == 401
    assert json.loads(bytes(response.body))["error"]["message"] == "登录状态无效或已过期。"
    request_id_var.set(None)
