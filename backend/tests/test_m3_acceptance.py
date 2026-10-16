"""M3 acceptance: T-006 through T-011 and T-016."""

import json
import logging
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.ai.broker import TaskBroker
from app.ai.mock_provider import MockScript, pop_mock_script, register_mock_script
from app.core.config import get_settings
from app.core.content import document_to_text
from app.core.logging import JsonFormatter

SECRET = "plain-secret-key-zz99"


def _assert_no_secret_fields(value: object) -> None:
    if isinstance(value, dict):
        assert "api_key" not in value
        assert "secret_ref" not in value
        for item in value.values():
            _assert_no_secret_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_fields(item)


def test_t006_unconfigured_model_does_not_generate(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    response = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, use_mock=False, mock_tokens=None),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert "模型设置" in response.json()["error"]["message"]
    assert _chapter_unchanged(auth_client, chapter)


def test_t007_mock_timeout_fails_without_touching_manuscript(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_behavior="timeout", mock_tokens=None),
    )
    assert created.status_code == 201, created.text
    task = _wait(auth_client, created.json()["id"])

    assert task["status"] == "failed"
    assert task["error_code"] == "MODEL_TIMEOUT"
    message = str(task["error_message_safe"])
    assert "超时" in message
    assert "成功" not in message
    assert task["output_text"] in {None, ""}
    events = _read_sse(auth_client, task["id"])
    names = [name for name, _data in events]
    assert "task.failed" in names
    assert names.count("task.failed") == 1
    assert "task.completed" not in names
    assert _chapter_unchanged(auth_client, chapter)


def test_t008_stream_tokens_are_ordered_and_completed_once(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_tokens=["甲", "乙", "丙"]),
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    task = _wait(auth_client, task_id)
    events = _read_sse(auth_client, task_id)
    tokens = [str(data["text"]) for name, data in events if name == "token"]
    completed = [data for name, data in events if name == "task.completed"]

    assert task["status"] == "completed"
    assert task["provider_mode"] == "mock"
    assert "模拟" in str(task["model_name"]) or task["model_name"] == "mock"
    assert task["output_text"] == "甲乙丙"
    assert tokens == ["甲", "乙", "丙"]
    assert len(completed) == 1
    assert completed[0]["output_text"] == "甲乙丙"
    assert _event_names(events).index("task.started") < _event_names(events).index("token")
    assert _event_names(events).index("token") < _event_names(events).index("task.completed")
    assert _chapter_unchanged(auth_client, chapter)


def test_t009_cancel_drops_late_tokens_and_keeps_manuscript(auth_client: TestClient) -> None:
    script = MockScript(hold_before=1)
    register_mock_script("gate-cancel", script)
    novel, chapter = _seed(auth_client)
    try:
        created = auth_client.post(
            "/api/v1/ai/tasks",
            json=_task(
                novel,
                chapter,
                mock_tokens=["甲", "乙"],
                mock_script_id="gate-cancel",
            ),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert script.reached.wait(5)
        running = auth_client.get(f"/api/v1/ai/tasks/{task_id}")
        assert running.status_code == 200
        assert running.json()["output_text"] == "甲"
        cancelled = auth_client.post(f"/api/v1/ai/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        script.release.set()
        assert script.processed.wait(5)
        final = auth_client.get(f"/api/v1/ai/tasks/{task_id}")
        assert final.json()["status"] == "cancelled"
        assert final.json()["output_text"] == "甲"
        events = _read_sse(auth_client, task_id)
        token_text = "".join(str(data["text"]) for name, data in events if name == "token")
        assert token_text == "甲"
        assert _event_names(events).count("task.cancelled") == 1
        assert "task.completed" not in _event_names(events)
        assert _chapter_unchanged(auth_client, chapter)
    finally:
        script.release.set()
        pop_mock_script("gate-cancel")


def test_t010_accept_updates_body_and_records_version(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, task_type="continue", mock_tokens=["新的一段"]),
    )
    task = _wait(auth_client, created.json()["id"])
    assert task["status"] == "completed"
    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["task"]["resolution"] == "accepted"
    saved = body["chapter"]
    assert saved["revision"] == chapter["revision"] + 1
    assert document_to_text(saved["content"]) == "原有正文\n\n新的一段"
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert versions.status_code == 200
    sources = [item["change_source"] for item in versions.json()]
    assert "ai_accepted" in sources
    note = next(item for item in versions.json() if item["change_source"] == "ai_accepted")
    assert "续写" in (note["change_note"] or "")

    conflict = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, saved, mock_tokens=["另一段"]),
    )
    other = _wait(auth_client, conflict.json()["id"])
    stale = auth_client.post(
        f"/api/v1/ai/tasks/{other['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["revision"] == saved["revision"]
    assert document_to_text(current.json()["content"]) == "原有正文\n\n新的一段"


def test_t011_reject_leaves_manuscript_unchanged(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, task_type="rewrite", mock_tokens=["不该写入"]),
    )
    task = _wait(auth_client, created.json()["id"])
    assert task["status"] == "completed"
    rejected = auth_client.post(f"/api/v1/ai/tasks/{task['id']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["resolution"] == "rejected"
    assert _chapter_unchanged(auth_client, chapter)
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert all(item["change_source"] != "ai_accepted" for item in versions.json())


def test_t016_api_key_is_absent_from_responses_and_logs(auth_client: TestClient) -> None:
    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(JsonFormatter().format(record))

    handler = ListHandler()
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        created = auth_client.post(
            "/api/v1/settings/models",
            json={
                "display_name": "外部服务",
                "provider_type": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "model_name": "demo-model",
                "api_key": SECRET,
                "timeout_seconds": 30,
            },
        )
        assert created.status_code == 201, created.text
        listed = auth_client.get("/api/v1/settings/models")
        assert listed.status_code == 200
        mock = auth_client.post(
            "/api/v1/settings/models",
            json={
                "display_name": "模拟",
                "provider_type": "mock",
                "model_name": "mock",
                "is_enabled": True,
            },
        )
        assert mock.status_code == 201, mock.text
        mock_test = auth_client.post(
            "/api/v1/settings/models/test",
            json={"config_id": mock.json()["id"]},
        )
        assert mock_test.status_code == 200, mock_test.text
        patched = auth_client.patch(
            f"/api/v1/settings/models/{created.json()['id']}",
            json={"display_name": "外部服务已改名"},
        )
        assert patched.status_code == 200, patched.text
        bodies = [created.text, listed.text, mock.text, mock_test.text, patched.text]
    finally:
        logger.removeHandler(handler)

    combined = "\n".join([*bodies, *records])
    assert SECRET not in combined
    for body in (created, listed, mock, mock_test, patched):
        _assert_no_secret_fields(body.json())
    assert created.json()["api_key_configured"] is True
    assert created.json()["api_key_hint"] == "••••zz99"
    assert created.json()["api_key_hint"] != SECRET

    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT secret_ref FROM model_configs")).scalars().all()
    engine.dispose()
    ciphertexts = [item for item in stored if isinstance(item, str)]
    assert ciphertexts
    assert all(SECRET not in item for item in ciphertexts)
    assert all(item is None or isinstance(item, str) for item in stored)


def test_model_routes_require_a_session(client: TestClient) -> None:
    response = client.get("/api/v1/settings/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    missing = client.post("/api/v1/ai/tasks", json={"novel_id": "x", "task_type": "continue"})
    assert missing.status_code == 401


def test_replace_selection_and_mock_indicator(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(
            novel,
            chapter,
            task_type="polish",
            selection_text="原有正文",
            mock_tokens=["润色后"],
        ),
    )
    task = _wait(auth_client, created.json()["id"])
    assert task["provider_mode"] == "mock"
    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "replace_selection"},
    )
    assert accepted.status_code == 200, accepted.text
    assert document_to_text(accepted.json()["chapter"]["content"]) == "润色后"


def test_broker_emits_heartbeat_while_waiting() -> None:
    import threading

    broker = TaskBroker()
    task_id = "task-heartbeat"
    events: list[tuple[str, dict[str, object]]] = []
    done = threading.Event()

    def listen() -> None:
        for event in broker.iter_events(task_id, 0.02):
            events.append(event)
            if event[0] == "task.completed":
                done.set()
                return

    thread = threading.Thread(target=listen)
    thread.start()
    time.sleep(0.08)
    assert any(name == "heartbeat" for name, _data in events)
    broker.publish(task_id, "task.completed", {"task_id": task_id, "status": "completed"})
    assert done.wait(2)
    thread.join(1)
    names = [name for name, _data in events]
    assert names.count("task.completed") == 1
    assert names[-1] == "task.completed"


def _seed(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": "长篇"}).json()
    created = client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章"},
    ).json()
    saved = client.put(
        f"/api/v1/chapters/{created['id']}",
        json={
            "revision": created["revision"],
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
    return novel, saved.json()


def _task(
    novel: dict[str, object],
    chapter: dict[str, object],
    **extra: object,
) -> dict[str, object]:
    body: dict[str, object] = {
        "novel_id": novel["id"],
        "chapter_id": chapter["id"],
        "task_type": "continue",
        "instruction": "往后写一句",
        "target_revision": chapter["revision"],
        "use_mock": True,
        "mock_tokens": ["候", "选"],
    }
    body.update(extra)
    if body.get("mock_tokens") is None:
        body.pop("mock_tokens")
    return body


def _wait(client: TestClient, task_id: object) -> dict[str, object]:
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


def _chapter_unchanged(client: TestClient, chapter: dict[str, object]) -> bool:
    current = client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.status_code == 200
    body = current.json()
    return body["revision"] == chapter["revision"] and body["content"] == chapter["content"]


def _read_sse(client: TestClient, task_id: object) -> list[tuple[str, dict[str, object]]]:
    with client.stream("GET", f"/api/v1/ai/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    return _parse_sse(text)


def _parse_sse(payload: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for frame in payload.split("\n\n"):
        if frame.strip() == "":
            continue
        name = ""
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if name and data:
            parsed = json.loads(data)
            assert isinstance(parsed, dict)
            events.append((name, parsed))
    return events


def _event_names(events: list[tuple[str, dict[str, object]]]) -> list[str]:
    return [name for name, _data in events]
