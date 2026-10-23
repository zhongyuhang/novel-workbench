"""A client that stops polling must not cancel work, and unused text stays adoptable."""

import time

from fastapi.testclient import TestClient

from app.ai.mock_provider import MockScript, pop_mock_script, register_mock_script
from app.core.content import document_to_text
from app.models.ai import AiTask


def test_poll_give_up_leaves_the_task_running_and_the_result_can_be_accepted(
    auth_client: TestClient,
) -> None:
    novel, chapter = _seed(auth_client)
    script = MockScript(hold_before=1)
    register_mock_script("poll-give-up", script)
    try:
        created = auth_client.post(
            "/api/v1/ai/tasks",
            json=_task(
                novel,
                chapter,
                mock_tokens=["甲", "乙"],
                mock_script_id="poll-give-up",
            ),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert script.reached.wait(5)
        watched = auth_client.get(f"/api/v1/ai/tasks/{task_id}")
        assert watched.status_code == 200
        assert watched.json()["status"] == "running"
        assert watched.json()["output_text"] == "甲"
        # The watch stops here. It must not cancel.
        still = auth_client.get(f"/api/v1/ai/tasks/{task_id}").json()
        assert still["status"] == "running"
        script.release.set()
        assert script.processed.wait(5)
        finished = _wait(auth_client, task_id)
        assert finished["status"] == "completed"
        assert finished["output_text"] == "甲乙"
        assert finished["resolution"] is None

        listed = auth_client.get("/api/v1/ai/tasks", params={"chapter_id": chapter["id"]})
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()] == [task_id]

        accepted = auth_client.post(
            f"/api/v1/ai/tasks/{task_id}/accept",
            json={"target_revision": chapter["revision"], "apply_mode": "append"},
        )
        assert accepted.status_code == 200, accepted.text
        assert document_to_text(accepted.json()["chapter"]["content"]) == "原有正文\n\n甲乙"
        hidden = auth_client.get("/api/v1/ai/tasks", params={"chapter_id": chapter["id"]})
        assert hidden.json() == []
    finally:
        script.release.set()
        pop_mock_script("poll-give-up")


def test_cancelled_task_with_output_stays_adoptable(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client)
    script = MockScript(hold_before=1)
    register_mock_script("cancel-keep", script)
    try:
        created = auth_client.post(
            "/api/v1/ai/tasks",
            json=_task(
                novel,
                chapter,
                mock_tokens=["已写", "后续"],
                mock_script_id="cancel-keep",
            ),
        )
        task_id = created.json()["id"]
        assert script.reached.wait(5)
        cancelled = auth_client.post(f"/api/v1/ai/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        script.release.set()
        assert script.processed.wait(5)
        final = _wait(auth_client, task_id)
        assert final["status"] == "cancelled"
        assert final["output_text"] == "已写"
        listed = auth_client.get("/api/v1/ai/tasks", params={"chapter_id": chapter["id"]}).json()
        assert listed[0]["id"] == task_id
        accepted = auth_client.post(
            f"/api/v1/ai/tasks/{task_id}/accept",
            json={"target_revision": chapter["revision"], "apply_mode": "append"},
        )
        assert accepted.status_code == 200, accepted.text
        assert document_to_text(accepted.json()["chapter"]["content"]) == "原有正文\n\n已写"
        assert accepted.json()["task"]["resolution"] == "accepted"
    finally:
        script.release.set()
        pop_mock_script("cancel-keep")


def test_empty_output_names_the_stop_and_keeps_the_finish_reason(
    auth_client: TestClient,
) -> None:
    novel, chapter = _seed(auth_client)
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_behavior="empty_length"),
    )
    assert created.status_code == 201, created.text
    task = _wait(auth_client, created.json()["id"])
    assert task["status"] == "failed"
    assert task["error_code"] == "EMPTY_OUTPUT"
    assert "长度上限" in str(task["error_message_safe"])
    assert "再试一次" in str(task["error_message_safe"])
    assert task["output_text"] in {None, ""}
    refused = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert refused.status_code == 409
    assert auth_client.get("/api/v1/ai/tasks", params={"chapter_id": chapter["id"]}).json() == []

    session = auth_client.app.state.session_factory()
    try:
        row = session.get(AiTask, task["id"])
        assert row is not None
        assert row.input_snapshot["provider_finish_reason"] == "length"
    finally:
        session.close()

    filtered = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_behavior="empty_filter"),
    )
    failed = _wait(auth_client, filtered.json()["id"])
    assert "内容过滤" in str(failed["error_message_safe"])
    assert "再试一次" not in str(failed["error_message_safe"])


def _seed(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": "找回候选"}).json()
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
        "instruction": "往后写",
        "target_revision": chapter["revision"],
        "use_mock": True,
    }
    body.update(extra)
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
