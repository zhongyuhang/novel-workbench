"""Continue and accept deposit rolling memory that context compile can see."""

import time

from fastapi.testclient import TestClient

FRAGMENT = "林晚说道：“夜色已深。”他来到江岸，发现一条伏笔。然后他离开了渡口。"


def test_empty_memory_compile_warns(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "还没记忆"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章"},
    ).json()
    compiled = _compile(auth_client, novel["id"], chapter, instruction="顺着写")

    assert compiled["warnings"]
    assert any("尚未生成章节摘要" in warning for warning in compiled["warnings"])
    assert all(item["kind"] != "summary" for item in compiled["items"])


def test_continue_accept_feeds_compile(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "长河"}).json()
    first = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章"},
    ).json()
    saved = auth_client.put(
        f"/api/v1/chapters/{first['id']}",
        json={
            "revision": first["revision"],
            "save_kind": "manual",
            "content": _doc("原有正文"),
        },
    )
    assert saved.status_code == 200, saved.text
    first = saved.json()
    second = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第二章"},
    ).json()

    before = _compile(auth_client, novel["id"], second, instruction="接着写林晚")
    before_included = [item for item in before["items"] if item["included"]]
    assert all(item["kind"] != "summary" for item in before["items"])
    assert any("尚未生成章节摘要" in warning for warning in before["warnings"])

    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel["id"],
            "chapter_id": first["id"],
            "task_type": "continue",
            "instruction": "往后写",
            "target_revision": first["revision"],
            "use_mock": True,
            "mock_tokens": [FRAGMENT],
        },
    )
    assert created.status_code == 201, created.text
    task = _wait_task(auth_client, created.json()["id"])
    assert task["status"] == "completed"
    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": first["revision"], "apply_mode": "append"},
    )
    assert accepted.status_code == 200, accepted.text
    revision = accepted.json()["chapter"]["revision"]

    summary = _wait_summary(auth_client, novel["id"], revision)
    assert "林晚" in summary["summary"]
    entities = _wait_named(auth_client, f"/api/v1/novels/{novel['id']}/entities", "林晚")
    assert any(entity["states"] for entity in entities if entity["name"] == "林晚")
    hooks = _wait_named(
        auth_client,
        f"/api/v1/novels/{novel['id']}/foreshadowing",
        "伏笔",
    )
    assert hooks

    after = _compile(auth_client, novel["id"], second, instruction="接着写林晚")
    included = [item for item in after["items"] if item["included"]]
    kinds = {item["kind"] for item in included}
    assert "summary" in kinds
    assert "entity" in kinds
    assert "foreshadowing" in kinds
    assert len(after["items"]) > len(before["items"])
    assert after["total_token_estimate"] > before["total_token_estimate"]
    assert len(included) > len(before_included)
    assert not any("尚未生成章节摘要" in warning for warning in after["warnings"])


def _compile(
    client: TestClient,
    novel_id: str,
    chapter: dict[str, object],
    *,
    instruction: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/ai/tasks/context/compile",
        json={
            "novel_id": novel_id,
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": instruction,
            "target_revision": chapter["revision"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _wait_task(client: TestClient, task_id: str) -> dict[str, object]:
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


def _wait_summary(client: TestClient, novel_id: str, revision: int) -> dict[str, object]:
    deadline = time.monotonic() + 8
    last: object = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/novels/{novel_id}/chapter-summaries")
        assert response.status_code == 200, response.text
        rows = response.json()
        last = rows
        assert isinstance(rows, list)
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("status") == "current"
                and row.get("source_revision") == revision
                and "林晚" in str(row.get("summary"))
            ):
                return row
        time.sleep(0.05)
    raise AssertionError(last)


def _wait_named(client: TestClient, path: str, needle: str) -> list[dict[str, object]]:
    deadline = time.monotonic() + 8
    last: object = None
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        rows = response.json()
        last = rows
        assert isinstance(rows, list)
        typed = [row for row in rows if isinstance(row, dict)]
        if any(needle in str(row.get("name") or row.get("description") or "") for row in typed):
            return typed
        time.sleep(0.05)
    raise AssertionError(last)


def _doc(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }
