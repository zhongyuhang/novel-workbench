"""E3 story bible: field-level revert, relations, and validity time."""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.memory import MemoryChangeProposal


def test_entity_update_revert_rolls_back_only_changed_fields(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client)
    entity = _entity(auth_client, str(novel["id"]), "林晚", "旧档案")
    proposal_id = _insert_proposal(
        auth_client,
        novel_id=str(novel["id"]),
        chapter_id=str(chapter["id"]),
        revision=int(chapter["revision"]),
        proposal_type="entity_update",
        payload={"target_entity_id": entity["id"], "name": "林晚晚"},
    )
    accepted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    changes = accepted.json()["payload"]["field_changes"]
    assert [item["field"] for item in changes] == ["name"]
    patched = auth_client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"profile": {"summary": "后来手改"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "林晚晚"

    reverted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/revert", json={})
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "reverted"
    stored = _find_entity(auth_client, str(novel["id"]), str(entity["id"]))
    assert stored["name"] == "林晚"
    assert stored["profile"]["summary"] == "后来手改"
    assert stored["status"] == "active"
    assert stored["states"] == []
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["revision"] == chapter["revision"]


def test_entity_update_revert_refuses_when_a_changed_field_was_edited(
    auth_client: TestClient,
) -> None:
    novel, chapter = _chapter(auth_client)
    entity = _entity(auth_client, str(novel["id"]), "林晚", "旧档案")
    proposal_id = _insert_proposal(
        auth_client,
        novel_id=str(novel["id"]),
        chapter_id=str(chapter["id"]),
        revision=int(chapter["revision"]),
        proposal_type="entity_update",
        payload={"target_entity_id": entity["id"], "name": "林晚晚"},
    )
    accepted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    renamed = auth_client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"name": "手改名"},
    )
    assert renamed.status_code == 200, renamed.text

    reverted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/revert", json={})
    assert reverted.status_code == 409, reverted.text
    assert "名称" in reverted.json()["error"]["message"]
    assert "没有改动" in reverted.json()["error"]["message"]
    stored = _find_entity(auth_client, str(novel["id"]), str(entity["id"]))
    assert stored["name"] == "手改名"
    assert stored["profile"]["summary"] == "旧档案"
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/memory-proposals")
    assert listed.json()[0]["status"] == "accepted"


def test_old_entity_update_without_field_changes_is_not_reverted(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client)
    entity = _entity(auth_client, str(novel["id"]), "林晚", "旧档案")
    renamed = auth_client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"name": "手改名", "profile": {"summary": "后来手改"}},
    )
    assert renamed.status_code == 200, renamed.text
    proposal_id = _insert_proposal(
        auth_client,
        novel_id=str(novel["id"]),
        chapter_id=str(chapter["id"]),
        revision=int(chapter["revision"]),
        proposal_type="entity_update",
        status="accepted",
        payload={
            "target_entity_id": entity["id"],
            "name": "林晚晚",
            "before": {
                "entity_type": "character",
                "name": "林晚",
                "aliases": [],
                "profile": {"summary": "旧档案"},
                "status": "active",
            },
            "applied": {
                "entity_id": entity["id"],
                "created_entity": False,
                "state_id": None,
                "event_id": None,
                "summary_id": None,
            },
        },
    )

    reverted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/revert", json={})
    assert reverted.status_code == 409, reverted.text
    assert "字段级" in reverted.json()["error"]["message"]
    stored = _find_entity(auth_client, str(novel["id"]), str(entity["id"]))
    assert stored["name"] == "手改名"
    assert stored["profile"]["summary"] == "后来手改"


def test_revert_refuses_when_the_old_name_is_now_taken(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client)
    entity = _entity(auth_client, str(novel["id"]), "林晚", "旧档案")
    proposal_id = _insert_proposal(
        auth_client,
        novel_id=str(novel["id"]),
        chapter_id=str(chapter["id"]),
        revision=int(chapter["revision"]),
        proposal_type="entity_update",
        payload={"target_entity_id": entity["id"], "name": "林晚晚"},
    )
    assert (
        auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/accept", json={}).status_code
        == 200
    )
    other = _entity(auth_client, str(novel["id"]), "林晚", "另一个人")
    reverted = auth_client.post(f"/api/v1/memory-proposals/{proposal_id}/revert", json={})
    assert reverted.status_code == 409, reverted.text
    assert "重名" in reverted.json()["error"]["message"]
    stored = _find_entity(auth_client, str(novel["id"]), str(entity["id"]))
    assert stored["name"] == "林晚晚"
    assert _find_entity(auth_client, str(novel["id"]), str(other["id"]))["name"] == "林晚"


def test_state_validity_can_stay_empty(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client)
    entity = _entity(auth_client, str(novel["id"]), "林晚", "守城")
    created = auth_client.post(
        f"/api/v1/entities/{entity['id']}/states",
        json={
            "chapter_id": chapter["id"],
            "state_data": {"summary": "左臂旧伤"},
            "evidence_quote": "左臂的旧伤又疼了起来。",
            "valid_from_text": "",
            "valid_until_text": None,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["valid_from_text"] is None
    assert body["valid_until_text"] is None
    assert body["source_revision"] == chapter["revision"]
    assert body["evidence_quote"] == "左臂的旧伤又疼了起来。"
    listed = _find_entity(auth_client, str(novel["id"]), str(entity["id"]))
    assert listed["states"][0]["valid_from_text"] is None
    updated = auth_client.patch(
        f"/api/v1/entity-states/{body['id']}",
        json={"valid_from_text": "入城次日"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["valid_from_text"] == "入城次日"
    assert updated.json()["valid_until_text"] is None
    assert updated.json()["state_data"]["summary"] == "左臂旧伤"

    other = auth_client.post("/api/v1/novels", json={"title": "另一本"}).json()
    other_chapter = auth_client.post(
        f"/api/v1/novels/{other['id']}/chapters",
        json={"title": "别章"},
    ).json()
    crossed = auth_client.post(
        f"/api/v1/entities/{entity['id']}/states",
        json={"chapter_id": other_chapter["id"], "state_data": {"summary": "不该写入"}},
    )
    assert crossed.status_code == 422


def test_relations_are_isolated_and_story_time_is_optional(auth_client: TestClient) -> None:
    first, chapter = _chapter(auth_client)
    second = auth_client.post("/api/v1/novels", json={"title": "另一本"}).json()
    left = _entity(auth_client, str(first["id"]), "林晚", "守城")
    right = _entity(auth_client, str(first["id"]), "城门", "南门")
    outsider = _entity(auth_client, str(second["id"]), "外人", "不该连上")
    created = auth_client.post(
        f"/api/v1/novels/{first['id']}/relations",
        json={
            "from_entity_id": left["id"],
            "to_entity_id": right["id"],
            "relation_type": "驻守",
            "story_time_text": "",
            "storyline": "主线",
            "source_chapter_id": chapter["id"],
            "evidence_quote": "林晚仍驻守在城门。",
        },
    )
    assert created.status_code == 201, created.text
    relation = created.json()
    assert relation["story_time_text"] is None
    assert relation["storyline"] == "主线"
    assert relation["source_chapter_id"] == chapter["id"]
    assert relation["source_revision"] == chapter["revision"]
    assert relation["evidence_quote"] == "林晚仍驻守在城门。"
    assert relation["from_entity_name"] == "林晚"
    assert relation["to_entity_name"] == "城门"

    hidden = auth_client.get(f"/api/v1/novels/{second['id']}/relations")
    assert hidden.status_code == 200, hidden.text
    assert hidden.json() == []
    crossed = auth_client.post(
        f"/api/v1/novels/{first['id']}/relations",
        json={
            "from_entity_id": left["id"],
            "to_entity_id": outsider["id"],
            "relation_type": "认识",
        },
    )
    assert crossed.status_code == 422
    same = auth_client.post(
        f"/api/v1/novels/{first['id']}/relations",
        json={
            "from_entity_id": left["id"],
            "to_entity_id": left["id"],
            "relation_type": "自指",
        },
    )
    assert same.status_code == 422
    filtered = auth_client.get(
        f"/api/v1/novels/{first['id']}/relations",
        params={"entity_id": left["id"], "storyline": "主"},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [relation["id"]]
    missing_storyline = auth_client.get(
        f"/api/v1/novels/{first['id']}/relations",
        params={"storyline": "支线"},
    )
    assert missing_storyline.json() == []
    removed = auth_client.delete(f"/api/v1/relations/{relation['id']}")
    assert removed.status_code == 204, removed.text
    assert auth_client.get(f"/api/v1/novels/{first['id']}/relations").json() == []


def test_compiler_uses_relation_and_validity_without_crossing_novels(
    auth_client: TestClient,
) -> None:
    novel, chapter = _chapter(auth_client, text="林晚说道：夜里城门已经关了。")
    other = auth_client.post("/api/v1/novels", json={"title": "另一本"}).json()
    other_chapter = auth_client.post(
        f"/api/v1/novels/{other['id']}/chapters",
        json={"title": "别章"},
    ).json()
    left = _entity(auth_client, str(novel["id"]), "林晚", "守城")
    right = _entity(auth_client, str(novel["id"]), "城门", "南门")
    state = auth_client.post(
        f"/api/v1/entities/{left['id']}/states",
        json={
            "chapter_id": chapter["id"],
            "state_data": {"summary": "左臂旧伤"},
            "valid_from_text": "入城次日",
        },
    )
    assert state.status_code == 201, state.text
    relation = auth_client.post(
        f"/api/v1/novels/{novel['id']}/relations",
        json={
            "from_entity_id": left["id"],
            "to_entity_id": right["id"],
            "relation_type": "驻守",
            "evidence_quote": "只在甲书的驻守证据",
        },
    )
    assert relation.status_code == 201, relation.text
    outsider = _entity(auth_client, str(other["id"]), "林晚", "乙书档案")
    decoy = _entity(auth_client, str(other["id"]), "城门", "乙书城门")
    leaked = auth_client.post(
        f"/api/v1/novels/{other['id']}/relations",
        json={
            "from_entity_id": outsider["id"],
            "to_entity_id": decoy["id"],
            "relation_type": "驻守",
            "evidence_quote": "乙书关系不该出现",
            "source_chapter_id": other_chapter["id"],
        },
    )
    assert leaked.status_code == 201, leaked.text

    compiled = auth_client.post(
        "/api/v1/ai/tasks/context/compile",
        json={
            "novel_id": novel["id"],
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "顺着林晚写",
            "target_revision": chapter["revision"],
        },
    )
    assert compiled.status_code == 200, compiled.text
    text = "\n".join(item["content"] for item in compiled.json()["items"] if item["included"])
    assert "只在甲书的驻守证据" in text
    assert "有效时间：自 入城次日 起" in text
    assert "故事时间未填写" in text
    assert "乙书关系不该出现" not in text
    assert "乙书档案" not in text


def _chapter(
    client: TestClient,
    text: str = "林晚说道：夜里城门已经关了。",
) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": "圣经作品"}).json()
    created = client.post(f"/api/v1/novels/{novel['id']}/chapters", json={"title": "第一章"})
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/chapters/{created.json()['id']}",
        json={
            "revision": created.json()["revision"],
            "save_kind": "manual",
            "content": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    return novel, saved.json()


def _entity(client: TestClient, novel_id: str, name: str, summary: str) -> dict[str, object]:
    created = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={
            "entity_type": "location" if name == "城门" else "character",
            "name": name,
            "profile": {"summary": summary},
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert isinstance(body, dict)
    return body


def _find_entity(client: TestClient, novel_id: str, entity_id: str) -> dict[str, object]:
    listed = client.get(f"/api/v1/novels/{novel_id}/entities")
    assert listed.status_code == 200, listed.text
    found = next(item for item in listed.json() if item["id"] == entity_id)
    assert isinstance(found, dict)
    return found


def _insert_proposal(
    client: TestClient,
    *,
    novel_id: str,
    chapter_id: str,
    revision: int,
    proposal_type: str,
    payload: dict[str, object],
    status: str = "pending",
) -> str:
    factory = client.app.state.session_factory
    session = factory()
    try:
        now = datetime.now(UTC)
        row = MemoryChangeProposal(
            id=str(uuid.uuid4()),
            novel_id=novel_id,
            source_chapter_id=chapter_id,
            source_revision=revision,
            proposal_type=proposal_type,
            payload=payload,
            evidence_quote="林晚说道：夜里城门已经关了。",
            certainty="confirmed",
            status=status,
            review_note=None,
            created_at=now,
            reviewed_at=now if status != "pending" else None,
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()
