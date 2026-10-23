"""A model timeout that already streamed text stays acceptable."""

import json
import time

from fastapi.testclient import TestClient

from app.core.content import document_to_text


def test_timeout_without_text_stays_failed(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_behavior="timeout", mock_tokens=None),
    )
    assert created.status_code == 201, created.text
    task = _wait(auth_client, created.json()["id"])

    assert task["status"] == "failed"
    assert task["partial"] is False
    assert task["error_code"] == "MODEL_TIMEOUT"
    assert task["output_text"] in {None, ""}
    refused = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "TASK_STATE"
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert document_to_text(current.json()["content"]) == "原有正文"


def test_timeout_with_buffer_can_be_accepted(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(
            novel,
            chapter,
            mock_behavior="timeout_after_tokens",
            mock_tokens=["夜色", "未散", "。"],
        ),
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    task = _wait(auth_client, task_id)

    assert task["status"] == "completed"
    assert task["partial"] is True
    assert task["resolution"] is None
    assert task["error_code"] == "MODEL_TIMEOUT"
    assert "采纳" in str(task["error_message_safe"])
    assert task["output_text"] == "夜色未散。"
    events = _read_sse(auth_client, task_id)
    completed = [data for name, data in events if name == "task.completed"]
    assert len(completed) == 1
    assert completed[0]["partial"] is True
    assert completed[0]["output_text"] == "夜色未散。"
    assert "task.failed" not in [name for name, _data in events]

    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task_id}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["task"]["resolution"] == "accepted"
    assert body["task"]["partial"] is True
    assert document_to_text(body["chapter"]["content"]) == "原有正文\n\n夜色未散。"


def _seed(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": "超时片段"}).json()
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
    }
    body.update(extra)
    if body.get("mock_tokens") is None:
        body.pop("mock_tokens", None)
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


def _read_sse(client: TestClient, task_id: object) -> list[tuple[str, dict[str, object]]]:
    with client.stream("GET", f"/api/v1/ai/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    events: list[tuple[str, dict[str, object]]] = []
    for frame in text.split("\n\n"):
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
