"""Model configuration center: defaults, test classification, SSRF, and backup."""

import logging
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.ai.registry import set_test_transport
from app.core.config import get_settings
from app.core.logging import JsonFormatter
from app.core.secrets import decrypt_api_key
from app.services.backup import create_backup, restore_backup

SECRET = "plain-secret-key-zz99"
HEADER_VALUE = "header-secret-zz99"


@pytest.fixture(autouse=True)
def _reset_transport() -> None:
    set_test_transport(None)
    yield
    set_test_transport(None)


def test_presets_are_data_and_not_a_closed_vendor_list(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/settings/models/presets")
    assert response.status_code == 200, response.text
    presets = response.json()
    by_id = {item["id"]: item for item in presets}
    assert {"openai", "deepseek", "qwen", "zhipu", "moonshot", "custom"} <= set(by_id)
    assert by_id["deepseek"]["default_base_url"].startswith("https://")
    assert by_id["custom"]["default_base_url"] == ""
    assert SECRET not in response.text


def test_create_hides_key_and_stores_ciphertext(auth_client: TestClient) -> None:
    created = _create_external(auth_client)
    assert created["api_key_configured"] is True
    assert created["api_key_hint"] == "••••zz99"
    assert created["last_test_status"] == "untested"
    assert created["is_default"] is False
    assert "api_key" not in created
    assert SECRET not in str(created)

    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT secret_ref FROM model_configs")).scalar_one()
    engine.dispose()
    assert isinstance(stored, str)
    assert SECRET not in stored
    assert decrypt_api_key(stored) == SECRET


def test_blank_key_keeps_secret_and_other_fields_do_not_expire_a_success(
    auth_client: TestClient,
) -> None:
    created = _create_external(auth_client)
    _install(lambda request: _chat_ok(request))
    tested = auth_client.post(f"/api/v1/settings/models/{created['id']}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["model_name"] == "demo-model"
    assert tested.json()["elapsed_ms"] >= 0

    renamed = auth_client.patch(
        f"/api/v1/settings/models/{created['id']}",
        json={"display_name": "只改显示名"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["api_key_configured"] is True
    assert renamed.json()["api_key_hint"] == "••••zz99"
    assert renamed.json()["last_test_status"] == "success"

    kept = auth_client.patch(
        f"/api/v1/settings/models/{created['id']}",
        json={"max_retries": 1},
    )
    assert kept.json()["last_test_status"] == "success"


def test_critical_change_requires_retest_and_default_rules(auth_client: TestClient) -> None:
    first = _create_external(auth_client, name="甲")
    second = _create_external(auth_client, name="乙", model_name="other-model")
    _install(lambda request: _chat_ok(request))
    assert auth_client.post(f"/api/v1/settings/models/{first['id']}/test").status_code == 200
    assert auth_client.post(f"/api/v1/settings/models/{second['id']}/test").status_code == 200

    blocked = auth_client.put(f"/api/v1/settings/models/{first['id']}/default")
    assert blocked.status_code == 200, blocked.text
    early = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "未测试",
            "provider_type": "mock",
            "model_name": "mock",
        },
    )
    refused = auth_client.put(f"/api/v1/settings/models/{early.json()['id']}/default")
    assert refused.status_code == 422
    assert "测试成功" in refused.json()["error"]["message"]

    stale = auth_client.patch(
        f"/api/v1/settings/models/{first['id']}",
        json={"base_url": "https://example.invalid/changed"},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["last_test_status"] == "stale"
    assert stale.json()["last_test_error_code"] == "CONFIG_CHANGED"
    assert stale.json()["is_default"] is False
    assert stale.json()["api_key_configured"] is True

    again = auth_client.put(f"/api/v1/settings/models/{first['id']}/default")
    assert again.status_code == 422

    chosen = auth_client.put(f"/api/v1/settings/models/{second['id']}/default")
    assert chosen.status_code == 200, chosen.text
    listed = auth_client.get("/api/v1/settings/models")
    defaults = [item for item in listed.json() if item["is_default"]]
    assert [item["id"] for item in defaults] == [second["id"]]

    protected = auth_client.delete(f"/api/v1/settings/models/{second['id']}")
    assert protected.status_code == 409
    assert protected.json()["error"]["code"] == "DEFAULT_MODEL_PROTECTED"
    other = auth_client.put(f"/api/v1/settings/models/{early.json()['id']}/default")
    assert other.status_code == 422
    tested_mock = auth_client.post(f"/api/v1/settings/models/{early.json()['id']}/test")
    assert tested_mock.status_code == 200, tested_mock.text
    switched = auth_client.put(f"/api/v1/settings/models/{early.json()['id']}/default")
    assert switched.status_code == 200, switched.text
    removed = auth_client.delete(f"/api/v1/settings/models/{second['id']}")
    assert removed.status_code == 204


def test_explicit_clear_removes_the_key(auth_client: TestClient) -> None:
    created = _create_external(auth_client)
    cleared = auth_client.patch(
        f"/api/v1/settings/models/{created['id']}",
        json={"clear_api_key": True},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["api_key_configured"] is False
    assert cleared.json()["api_key_hint"] is None
    tested = auth_client.post(f"/api/v1/settings/models/{created['id']}/test")
    assert tested.status_code == 422
    assert tested.json()["error"]["code"] == "MODEL_CONFIG_INVALID"
    listed = auth_client.get(f"/api/v1/settings/models/{created['id']}")
    assert listed.json()["last_test_error_code"] == "KEY_MISSING"


def test_upstream_errors_are_classified_without_leaking_the_key(auth_client: TestClient) -> None:
    created = _create_external(auth_client, headers={"X-Trace": HEADER_VALUE})
    assert created["custom_header_names"] == ["X-Trace"]
    assert HEADER_VALUE not in str(created)
    cases = [
        (_auth_denied, "MODEL_AUTH", "AUTH_FAILED"),
        (_model_missing, "MODEL_NOT_FOUND", "MODEL_NOT_FOUND"),
        (_missing_path, "MODEL_BASE_URL", "BASE_URL_INVALID"),
        (_limited, "MODEL_RATE_LIMIT", "RATE_LIMIT"),
        (_timeout, "MODEL_TIMEOUT", "TIMEOUT"),
        (_connect, "MODEL_BASE_URL", "BASE_URL_INVALID"),
        (_network, "MODEL_UNAVAILABLE", "NETWORK"),
        (_redirect, "MODEL_BASE_URL", "BASE_URL_INVALID"),
        (_incompatible, "MODEL_BAD_RESPONSE", "INCOMPATIBLE_RESPONSE"),
    ]
    for handler, http_code, stored in cases:
        _install(handler)
        response = auth_client.post(f"/api/v1/settings/models/{created['id']}/test")
        assert response.status_code >= 400, response.text
        assert response.json()["error"]["code"] == http_code
        assert SECRET not in response.text
        assert HEADER_VALUE not in response.text
        current = auth_client.get(f"/api/v1/settings/models/{created['id']}")
        assert current.json()["last_test_status"] == "failed"
        assert current.json()["last_test_error_code"] == stored


def test_successful_minimal_request_sends_headers_and_one_token(auth_client: TestClient) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["trace"] = request.headers.get("x-trace")
        seen["body"] = request.read().decode()
        return _chat_ok(request)

    created = _create_external(auth_client, headers={"X-Trace": HEADER_VALUE})
    _install(handler)
    tested = auth_client.post(f"/api/v1/settings/models/{created['id']}/test")
    assert tested.status_code == 200, tested.text
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["trace"] == HEADER_VALUE
    body = str(seen["body"])
    assert '"max_tokens":1' in body or '"max_tokens": 1' in body
    assert "demo-model" in body
    assert SECRET not in tested.text

    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT encrypted_custom_headers FROM model_configs WHERE id = :id"),
            {"id": created["id"]},
        ).scalar_one()
    engine.dispose()
    assert isinstance(stored, str)
    assert HEADER_VALUE not in stored
    assert HEADER_VALUE in decrypt_api_key(stored)


def test_ssrf_blocks_loopback_metadata_and_private_addresses(auth_client: TestClient) -> None:
    for base_url in (
        "http://127.0.0.1/v1",
        "http://169.254.169.254/",
        "http://10.1.2.3/v1",
        "http://192.168.0.8/v1",
        "http://metadata.google.internal/v1",
        "http://0177.0.0.1/v1",
    ):
        response = auth_client.post(
            "/api/v1/settings/models",
            json=_external_body(base_url=base_url),
        )
        assert response.status_code == 422, response.text
        assert "安全策略" in response.json()["error"]["message"]
        assert SECRET not in response.text


def test_allowlist_permits_a_local_model(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_BASE_URL_ALLOWLIST", "127.0.0.1")
    get_settings.cache_clear()
    created = auth_client.post(
        "/api/v1/settings/models",
        json=_external_body(base_url="http://127.0.0.1:9/v1"),
    )
    assert created.status_code == 201, created.text
    _install(lambda request: _chat_ok(request))
    tested = auth_client.post(f"/api/v1/settings/models/{created.json()['id']}/test")
    assert tested.status_code == 200, tested.text


def test_logs_do_not_include_the_key(auth_client: TestClient) -> None:
    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(JsonFormatter().format(record))

    handler = ListHandler()
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        created = _create_external(auth_client)
        _install(_auth_denied)
        failed = auth_client.post(f"/api/v1/settings/models/{created['id']}/test")
        assert failed.status_code >= 400
    finally:
        logger.removeHandler(handler)
    assert SECRET not in "\n".join(records)


def test_backup_keeps_ciphertext_that_decrypts_after_restore(
    auth_client: TestClient, tmp_path: Path
) -> None:
    created = _create_external(auth_client)
    manifest = create_backup(get_settings())
    backup_dir = get_settings().resolved_data_dir / "backups" / manifest.backup_id
    database = backup_dir / "database.sqlite"
    blob = database.read_bytes()
    assert SECRET.encode() not in blob
    payload = (backup_dir / "manifest.json").read_text(encoding="utf-8")
    assert "APP_SECRET_ENCRYPTION_KEY" in payload
    assert get_settings().app_secret_encryption_key not in payload
    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT secret_ref FROM model_configs").fetchone()
    assert stored is not None
    assert decrypt_api_key(str(stored[0])) == SECRET

    restored = tmp_path / "restored.db"
    restore_backup(backup_dir, restored)
    with sqlite3.connect(restored) as connection:
        again = connection.execute(
            "SELECT secret_ref FROM model_configs WHERE id = ?",
            (created["id"],),
        ).fetchone()
    assert again is not None
    assert decrypt_api_key(str(again[0])) == SECRET


def test_tasks_record_the_default_model_and_other_modules_accept_an_id(
    auth_client: TestClient,
) -> None:
    mock = auth_client.post(
        "/api/v1/settings/models",
        json={"display_name": "模拟默认", "provider_type": "mock", "model_name": "mock-writer"},
    )
    assert mock.status_code == 201, mock.text
    mock_id = mock.json()["id"]
    assert auth_client.post(f"/api/v1/settings/models/{mock_id}/test").status_code == 200
    assert auth_client.put(f"/api/v1/settings/models/{mock_id}/default").status_code == 200

    novel = auth_client.post("/api/v1/novels", json={"title": "选用模型"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章"},
    ).json()
    saved = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "save_kind": "manual",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "原有正文"}]}
                ],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    chapter = saved.json()
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel["id"],
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "续一句",
            "target_revision": chapter["revision"],
            "use_mock": False,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["model_config_id"] == mock_id
    assert created.json()["model_name"] == "mock-writer"
    task_id = created.json()["id"]
    deadline_body = _wait(auth_client, task_id)
    assert deadline_body["model_config_id"] == mock_id
    with auth_client.stream("GET", f"/api/v1/ai/tasks/{task_id}/events") as streamed:
        assert streamed.status_code == 200
        raw = "".join(streamed.iter_text())
    assert "task.completed" in raw or "task.started" in raw
    assert SECRET not in raw

    analyzed = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "model_config_id": mock_id},
    )
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["model_config_id"] == mock_id
    conflicts = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/conflict-check",
        json={"use_mock": False, "model_config_id": mock_id},
    )
    assert conflicts.status_code == 200, conflicts.text
    assert conflicts.json()["model_config_id"] == mock_id
    quality = auth_client.post(
        f"/api/v1/novels/{novel['id']}/quality-check",
        json={"use_model": True, "model_config_id": mock_id},
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["model_config_id"] == mock_id
    assert quality.json()["manuscript_changed"] is False
    outline = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/outline-candidate",
        json={"use_mock": False, "include_scenes": False},
    )
    assert outline.status_code == 200, outline.text
    assert outline.json()["model_config_id"] == mock_id
    assert outline.json()["model_name"] == "mock-writer"
    assert outline.json()["written"] is False
    assert outline.json()["manuscript_changed"] is False


def _wait(client: TestClient, task_id: str) -> dict[str, object]:
    import time

    deadline = time.monotonic() + 8
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/ai/tasks/{task_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body, dict)
        last = body
        if body.get("status") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.02)
    raise AssertionError(last)


def _create_external(
    client: TestClient,
    *,
    name: str = "外部服务",
    model_name: str = "demo-model",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/settings/models",
        json=_external_body(name, model_name, headers),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _external_body(
    name: str = "外部服务",
    model_name: str = "demo-model",
    headers: dict[str, str] | None = None,
    base_url: str = "https://example.invalid/v1",
) -> dict[str, object]:
    body: dict[str, object] = {
        "display_name": name,
        "provider": "custom",
        "provider_type": "openai_compatible",
        "base_url": base_url,
        "model_name": model_name,
        "api_key": SECRET,
        "timeout_seconds": 30,
    }
    if headers is not None:
        body["custom_headers"] = headers
    return body


def _install(handler: object) -> None:
    set_test_transport(httpx.MockTransport(handler))  # type: ignore[arg-type]


def _chat_ok(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        json={
            "model": "demo-model",
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
        },
    )


def _auth_denied(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(401, json={"error": {"message": f"rejected {SECRET}"}})


def _model_missing(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        404,
        json={"error": {"code": "model_not_found", "message": SECRET}},
    )


def _missing_path(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(404, text="no route")


def _limited(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(429, json={"error": "slow down"})


def _timeout(request: httpx.Request) -> httpx.Response:
    del request
    raise httpx.ReadTimeout("timed out")


def _connect(request: httpx.Request) -> httpx.Response:
    del request
    raise httpx.ConnectError("dns")


def _network(request: httpx.Request) -> httpx.Response:
    del request
    raise httpx.ReadError("reset")


def _redirect(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(302, headers={"location": "http://169.254.169.254/"})


def _incompatible(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(200, json={"ok": True})
