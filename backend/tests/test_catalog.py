"""Novel, volume, and chapter behavior against SQLite."""

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.content import word_count
from app.main import create_app

PARAGRAPHS = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "第一段"}]},
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "第二段"},
                {"type": "hardBreak"},
                {"type": "text", "text": "仍在这一段"},
            ],
        },
    ],
}


def test_catalog_requires_session(client: TestClient) -> None:
    response = client.get("/api/v1/novels")

    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"]
    assert "traceback" not in response.text.lower()


def test_t001_novel_survives_restart(auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/v1/novels",
        json={"title": " 持久化作品 ", "genre": "笔记", "status": "active"},
    )
    assert created.status_code == 201, created.text
    novel = created.json()
    assert novel["title"] == "持久化作品"
    assert novel["status"] == "active"

    listed = auth_client.get("/api/v1/novels")
    assert listed.status_code == 200
    assert any(item["id"] == novel["id"] for item in listed.json())

    with TestClient(create_app()) as restarted:
        session = restarted.post("/api/v1/auth/session", json={"password": ""})
        assert session.status_code == 200, session.text
        restarted.headers["Authorization"] = f"Bearer {session.json()['access_token']}"
        again = restarted.get("/api/v1/novels")
        assert again.status_code == 200
        match = next(item for item in again.json() if item["id"] == novel["id"])
        assert match["title"] == "持久化作品"
        assert match["genre"] == "笔记"


def test_soft_deleted_novel_is_hidden(auth_client: TestClient) -> None:
    created = auth_client.post("/api/v1/novels", json={"title": "将删除"}).json()
    deleted = auth_client.delete(f"/api/v1/novels/{created['id']}")
    assert deleted.status_code == 204

    listed = auth_client.get("/api/v1/novels")
    assert all(item["id"] != created["id"] for item in listed.json())
    missing = auth_client.get(f"/api/v1/novels/{created['id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_archive_novel_keeps_it_in_the_list(auth_client: TestClient) -> None:
    created = auth_client.post("/api/v1/novels", json={"title": "归档对象"}).json()
    archived = auth_client.patch(
        f"/api/v1/novels/{created['id']}",
        json={"status": "archived", "synopsis": "一段简介"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["synopsis"] == "一段简介"

    listed = auth_client.get("/api/v1/novels")
    archived = [item for item in listed.json() if item["id"] == created["id"]]
    assert len(archived) == 1
    assert archived[0]["status"] == "archived"


def test_t002_chapter_body_roundtrip(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "正文作品"}).json()
    created = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "开篇"},
    )
    assert created.status_code == 201, created.text
    chapter = created.json()
    assert chapter["revision"] == 1
    assert chapter["content_format"] == "tiptap_json"
    assert chapter["content_format_version"] == 1
    assert chapter["content"]["type"] == "doc"

    saved = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={"revision": 1, "content": PARAGRAPHS, "content_format": "tiptap_json"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["revision"] == 2
    assert body["content"] == PARAGRAPHS
    assert body["word_count"] == word_count(PARAGRAPHS)
    assert body["word_count"] > len("第一段")

    loaded = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["content"] == PARAGRAPHS
    assert loaded.json()["word_count"] == body["word_count"]

    with TestClient(create_app()) as restarted:
        session = restarted.post("/api/v1/auth/session", json={"password": ""})
        restarted.headers["Authorization"] = f"Bearer {session.json()['access_token']}"
        persisted = restarted.get(f"/api/v1/chapters/{chapter['id']}")
        assert persisted.status_code == 200
        assert persisted.json()["content"] == PARAGRAPHS
        assert persisted.json()["revision"] == 2


def test_t004_revision_conflict_does_not_overwrite(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "冲突作品"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "一章"},
    ).json()
    first_body = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "先写入"}]}],
    }
    second_body = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "后写入"}]}],
    }

    first = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={"revision": chapter["revision"], "content": first_body},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == chapter["revision"] + 1

    conflict = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={"revision": chapter["revision"], "content": second_body},
    )
    assert conflict.status_code == 409
    error = conflict.json()["error"]
    assert error["code"] == "REVISION_CONFLICT"
    assert error["message"] == "章节已在其他操作中更新，请刷新并比较差异。"
    assert error["request_id"]

    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["content"] == first_body
    assert current.json()["revision"] == chapter["revision"] + 1
    assert "后写入" not in current.text


def test_put_requires_revision(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "缺修订号"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "一章"},
    ).json()

    rejected = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={"content": {"type": "doc", "content": []}},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={"revision": 1, "content": {"type": "html"}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_DOCUMENT"


def test_t014_chapter_list_is_scoped_to_the_novel(auth_client: TestClient) -> None:
    first = auth_client.post("/api/v1/novels", json={"title": "作品甲"}).json()
    second = auth_client.post("/api/v1/novels", json={"title": "作品乙"}).json()
    chapter_a = auth_client.post(
        f"/api/v1/novels/{first['id']}/chapters",
        json={"title": "甲的章节"},
    ).json()
    chapter_b = auth_client.post(
        f"/api/v1/novels/{second['id']}/chapters",
        json={"title": "乙的章节"},
    ).json()

    listed = auth_client.get(f"/api/v1/novels/{first['id']}/chapters")
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()]
    assert ids == [chapter_a["id"]]
    assert chapter_b["id"] not in ids
    assert all(item["novel_id"] == first["id"] for item in listed.json())
    assert "content" not in listed.json()[0]

    foreign_volume = auth_client.post(
        f"/api/v1/novels/{second['id']}/volumes",
        json={"title": "乙的卷"},
    ).json()
    rejected = auth_client.post(
        f"/api/v1/novels/{first['id']}/chapters",
        json={"title": "错卷", "volume_id": foreign_volume["id"]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_REFERENCE"


def test_volume_reorder_and_chapter_move_follow_sort_order(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "结构"}).json()
    first = auth_client.post(
        f"/api/v1/novels/{novel['id']}/volumes",
        json={"title": "卷一"},
    ).json()
    second = auth_client.post(
        f"/api/v1/novels/{novel['id']}/volumes",
        json={"title": "卷二"},
    ).json()
    assert [first["sort_order"], second["sort_order"]] == [0, 1]

    reordered = auth_client.post(
        "/api/v1/volumes/reorder",
        json={"novel_id": novel["id"], "volume_ids": [second["id"], first["id"]]},
    )
    assert reordered.status_code == 200, reordered.text
    assert [item["id"] for item in reordered.json()] == [second["id"], first["id"]]
    assert [item["sort_order"] for item in reordered.json()] == [0, 1]

    opening = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "先", "volume_id": second["id"]},
    ).json()
    later = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "后", "volume_id": second["id"]},
    ).json()
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/chapters")
    in_volume = [item for item in listed.json() if item["volume_id"] == second["id"]]
    assert [item["title"] for item in in_volume] == ["先", "后"]
    assert [item["sort_order"] for item in in_volume] == [0, 1]

    moved = auth_client.post(
        f"/api/v1/chapters/{later['id']}/move",
        json={"volume_id": second["id"], "sort_order": 0},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["revision"] == later["revision"]
    listed_again = auth_client.get(f"/api/v1/novels/{novel['id']}/chapters")
    in_volume = [item for item in listed_again.json() if item["volume_id"] == second["id"]]
    assert [item["title"] for item in in_volume] == ["后", "先"]

    copied = auth_client.post(f"/api/v1/chapters/{opening['id']}/duplicate")
    assert copied.status_code == 201, copied.text
    assert copied.json()["title"] == "先 副本"
    assert copied.json()["revision"] == 1
    assert copied.json()["content"] == opening["content"]
    assert copied.json()["id"] != opening["id"]


def test_access_password_rejects_mismatch(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "correct-passphrase")
    get_settings.cache_clear()

    denied = client.post("/api/v1/auth/session", json={"password": "wrong-passphrase"})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "INVALID_PASSWORD"

    allowed = client.post("/api/v1/auth/session", json={"password": "correct-passphrase"})
    assert allowed.status_code == 200
    assert allowed.json()["token_type"] == "bearer"
