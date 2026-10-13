"""Chapter snapshots, restore, and optimistic locking."""

from fastapi.testclient import TestClient


def _paragraph(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _create_chapter(
    client: TestClient,
    title: str = "一章",
) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": "版本作品"}).json()
    chapter = client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": title},
    ).json()
    return novel, chapter


def _save(
    client: TestClient,
    chapter_id: str,
    revision: int,
    content: dict[str, object],
    *,
    save_kind: str = "manual",
) -> object:
    return client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={
            "revision": revision,
            "content": content,
            "content_format": "tiptap_json",
            "save_kind": save_kind,
        },
    )


def test_versions_and_export_require_session(client: TestClient) -> None:
    versions = client.get("/api/v1/chapters/missing/versions")
    restore = client.post(
        "/api/v1/chapters/missing/restore",
        json={"revision": 1, "version_id": "missing"},
    )
    exported = client.post("/api/v1/novels/missing/export", json={"format": "markdown"})

    assert versions.status_code == 401
    assert restore.status_code == 401
    assert exported.status_code == 401
    assert versions.json()["error"]["code"] == "UNAUTHENTICATED"


def test_manual_save_snapshots_and_autosave_does_not(auth_client: TestClient) -> None:
    _novel, chapter = _create_chapter(auth_client)
    autosaved = _save(
        auth_client,
        chapter["id"],
        chapter["revision"],
        _paragraph("自动保存的句子"),
        save_kind="autosave",
    )
    assert autosaved.status_code == 200, autosaved.text
    assert autosaved.json()["revision"] == 2
    assert autosaved.json()["content"]["content"][0]["content"][0]["text"] == "自动保存的句子"

    listed = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert listed.status_code == 200, listed.text
    assert listed.json() == []

    confirmed = _save(
        auth_client,
        chapter["id"],
        autosaved.json()["revision"],
        _paragraph("自动保存的句子"),
        save_kind="manual",
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["revision"] == 2

    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert versions.status_code == 200, versions.text
    body = versions.json()
    assert len(body) == 1
    assert body[0]["revision"] == 2
    assert body[0]["change_source"] == "manual"
    assert body[0]["content_format"] == "tiptap_json"
    assert body[0]["content_format_version"] == 1
    assert body[0]["preview"] == "自动保存的句子"
    assert "content_snapshot" not in body[0]

    changed = _save(
        auth_client,
        chapter["id"],
        confirmed.json()["revision"],
        _paragraph("手动改过的句子"),
        save_kind="manual",
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 3
    again = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert [item["revision"] for item in again.json()] == [3, 2]
    assert again.json()[0]["preview"] == "手动改过的句子"


def test_rejected_save_does_not_record_a_snapshot(auth_client: TestClient) -> None:
    _novel, chapter = _create_chapter(auth_client)
    first = _save(auth_client, chapter["id"], chapter["revision"], _paragraph("先写入"))
    assert first.status_code == 200, first.text
    conflict = _save(auth_client, chapter["id"], chapter["revision"], _paragraph("不该留下"))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"

    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["content"] == _paragraph("先写入")
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    assert len(versions.json()) == 1
    assert versions.json()[0]["preview"] == "先写入"
    assert "不该留下" not in versions.text


def test_version_preview_is_truncated(auth_client: TestClient) -> None:
    _novel, chapter = _create_chapter(auth_client)
    long_text = "长" * 500
    saved = _save(auth_client, chapter["id"], chapter["revision"], _paragraph(long_text))
    assert saved.status_code == 200, saved.text
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions")
    preview = versions.json()[0]["preview"]
    assert preview.endswith("…")
    assert len(preview) == 120
    assert long_text not in versions.text
    loaded = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert loaded.json()["content"]["content"][0]["content"][0]["text"] == long_text


def test_t005_restore_creates_new_revision_and_keeps_old_versions(auth_client: TestClient) -> None:
    _novel, chapter = _create_chapter(auth_client, title="可恢复")
    first = _save(auth_client, chapter["id"], 1, _paragraph("第一稿"))
    assert first.status_code == 200, first.text
    second = _save(auth_client, chapter["id"], first.json()["revision"], _paragraph("第二稿"))
    assert second.status_code == 200, second.text
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    assert [item["revision"] for item in versions] == [3, 2]
    target = next(item for item in versions if item["revision"] == 2)

    restored = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/restore",
        json={"revision": second.json()["revision"], "version_id": target["id"]},
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["revision"] == second.json()["revision"] + 1
    assert body["content"] == _paragraph("第一稿")
    assert body["title"] == "可恢复"
    assert "第二稿" not in body["content"]["content"][0]["content"][0]["text"]

    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["content"] == _paragraph("第一稿")
    assert current.json()["revision"] == 4

    kept = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    by_revision = {item["revision"]: item for item in kept}
    assert set(by_revision) == {2, 3, 4}
    assert by_revision[2]["preview"] == "第一稿"
    assert by_revision[2]["change_source"] == "manual"
    assert by_revision[3]["preview"] == "第二稿"
    assert by_revision[4]["change_source"] == "restore"
    assert by_revision[4]["preview"] == "第一稿"
    assert by_revision[4]["change_note"] == "恢复自修订 2"
    assert by_revision[2]["id"] == target["id"]


def test_restore_conflict_does_not_overwrite(auth_client: TestClient) -> None:
    _novel, chapter = _create_chapter(auth_client)
    saved = _save(auth_client, chapter["id"], 1, _paragraph("已确认"))
    version_id = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()[0]["id"]
    newer = _save(auth_client, chapter["id"], saved.json()["revision"], _paragraph("更新的正文"))
    assert newer.status_code == 200, newer.text

    conflict = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/restore",
        json={"revision": saved.json()["revision"], "version_id": version_id},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"

    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["revision"] == newer.json()["revision"]
    assert current.json()["content"] == _paragraph("更新的正文")
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    assert [item["change_source"] for item in versions] == ["manual", "manual"]


def test_versions_stay_inside_one_chapter(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "隔离"}).json()
    first = auth_client.post(f"/api/v1/novels/{novel['id']}/chapters", json={"title": "甲"}).json()
    second = auth_client.post(f"/api/v1/novels/{novel['id']}/chapters", json={"title": "乙"}).json()
    saved_first = _save(auth_client, first["id"], 1, _paragraph("甲的正文"))
    saved_second = _save(auth_client, second["id"], 1, _paragraph("乙的正文"))
    assert saved_first.status_code == 200
    assert saved_second.status_code == 200
    foreign_version = auth_client.get(f"/api/v1/chapters/{second['id']}/versions").json()[0]

    missing = auth_client.get("/api/v1/chapters/missing/versions")
    assert missing.status_code == 404

    rejected = auth_client.post(
        f"/api/v1/chapters/{first['id']}/restore",
        json={"revision": saved_first.json()["revision"], "version_id": foreign_version["id"]},
    )
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "NOT_FOUND"
    current = auth_client.get(f"/api/v1/chapters/{first['id']}")
    assert current.json()["content"] == _paragraph("甲的正文")
    assert current.json()["revision"] == saved_first.json()["revision"]
