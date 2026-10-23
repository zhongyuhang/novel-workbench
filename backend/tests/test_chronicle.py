"""Chronicle order, manual events, and plans that stay candidates until accept."""

import io
import json
import zipfile
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.registry import set_test_transport

SECRET = "plain-secret-key-zz99"
PARAGRAPH = {
    "type": "doc",
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "夜里城门已经关了。"}]}],
}


@pytest.fixture(autouse=True)
def _clear_transport() -> Iterator[None]:
    set_test_transport(None)
    yield
    set_test_transport(None)


def test_chronicle_requires_a_session(client: TestClient) -> None:
    response = client.get("/api/v1/novels/missing/chronicle")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_chronicle_orders_by_story_time_and_keeps_links(auth_client: TestClient) -> None:
    novel, chapter = _novel_with_chapter(auth_client)
    character = _entity(auth_client, novel["id"], "character", "阿禾")
    place = _entity(auth_client, novel["id"], "location", "城门")
    arc = auth_client.post(
        f"/api/v1/novels/{novel['id']}/story-arcs",
        json={"arc_type": "main", "title": "入城"},
    )
    assert arc.status_code == 201, arc.text
    hook = auth_client.post(
        f"/api/v1/novels/{novel['id']}/foreshadowing",
        json={
            "introduced_chapter_id": chapter["id"],
            "description": "旧伤还会再疼",
            "status": "open",
        },
    )
    assert hook.status_code == 201, hook.text
    other = _novel(auth_client, "另一本")
    other_chapter = auth_client.post(
        f"/api/v1/novels/{other['id']}/chapters",
        json={"title": "外章"},
    )
    assert other_chapter.status_code == 201, other_chapter.text

    late = _create(
        auth_client,
        novel["id"],
        description="第十天才离开",
        event_time_text="第10天",
    )
    early = _create(
        auth_client,
        novel["id"],
        description="第一天入城",
        event_time_text="第1天",
        participants=["阿禾"],
        chapter_id=str(chapter["id"]),
        story_arc_id=arc.json()["id"],
        foreshadowing_id=hook.json()["id"],
    )
    dated = _create(
        auth_client,
        novel["id"],
        description="有公历的事",
        event_time_text="2020-01-02",
    )
    loose = _create(
        auth_client,
        novel["id"],
        description="时间还没定",
        sort_order=1,
    )
    later_loose = _create(auth_client, novel["id"], description="更靠后的未定事件")
    assert early["participant_entity_ids"] == [character["id"]]
    assert early["chapter_id"] == chapter["id"]
    assert early["story_arc_id"] == arc.json()["id"]
    assert early["foreshadowing_id"] == hook.json()["id"]
    stored_chapter = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert stored_chapter["revision"] == chapter["revision"]

    blocked = auth_client.post(
        f"/api/v1/novels/{novel['id']}/events",
        json={"description": "借了别人的章节", "chapter_id": other_chapter.json()["id"]},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "INVALID_REFERENCE"
    place_link = auth_client.post(
        f"/api/v1/novels/{novel['id']}/events",
        json={"description": "把门当成人物", "participant_entity_ids": [place["id"]]},
    )
    assert place_link.status_code == 422

    view = auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle")
    assert view.status_code == 200, view.text
    descriptions = [item["description"] for item in view.json()["events"]]
    assert descriptions == [
        "有公历的事",
        "第一天入城",
        "第十天才离开",
        "时间还没定",
        "更靠后的未定事件",
    ]
    assert view.json()["events"][1]["id"] == early["id"]
    assert late["id"] in {item["id"] for item in view.json()["events"]}
    assert loose["sort_order"] == 1
    assert later_loose["event_time_text"] is None

    impact = auth_client.get(
        f"/api/v1/novels/{novel['id']}/material-impact",
        params={"kind": "event", "target_id": early["id"]},
    )
    assert impact.status_code == 200, impact.text
    kinds = {item["kind"] for item in impact.json()["affected"]}
    assert {"chapter", "entity", "story_arc", "foreshadowing"} <= kinds
    assert impact.json()["formal_memory_changed"] is False

    moved = auth_client.patch(
        f"/api/v1/events/{dated['id']}",
        json={"event_time_text": "第2天"},
    )
    assert moved.status_code == 200, moved.text
    retimed = [
        item["description"]
        for item in auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"]
    ]
    assert retimed[:3] == ["第一天入城", "有公历的事", "第十天才离开"]

    removed = auth_client.delete(f"/api/v1/events/{later_loose['id']}")
    assert removed.status_code == 204
    remaining = auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"]
    assert all(item["id"] != later_loose["id"] for item in remaining)
    stored_body = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert stored_body["content"] == chapter["content"]


def test_plan_stays_a_candidate_until_accept(auth_client: TestClient) -> None:
    novel, chapter = _novel_with_chapter(auth_client)
    _entity(auth_client, novel["id"], "character", "阿禾")
    planned = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chronicle/plan",
        json={"hint": "记住门关上的声音", "use_mock": True},
    )
    assert planned.status_code == 200, planned.text
    body = planned.json()
    assert body["formal_material_changed"] is False
    assert body["manuscript_changed"] is False
    assert body["simulated"] is True
    assert body["provider_mode"] == "mock"
    assert SECRET not in planned.text
    candidates = body["candidates"]
    titles = [item["title"] for item in candidates]
    assert titles == ["规划：事情开始", "规划：事情往后"]
    assert "阿禾" in candidates[0]["description"]
    assert "记住门关上的声音" in candidates[0]["description"]
    assert candidates[0]["status"] == "pending"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"] == []
    stored_chapter = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert stored_chapter["revision"] == chapter["revision"]

    deferred = auth_client.post(f"/api/v1/chronicle-candidates/{candidates[0]['id']}/defer")
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["formal_material_changed"] is False
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/events").json() == []

    accepted = auth_client.post(
        f"/api/v1/chronicle-candidates/{candidates[0]['id']}/accept",
        json={
            "event": {
                "description": "门关上之后才开始",
                "event_time_text": "第4天",
                "participants": ["阿禾"],
                "chapter_id": chapter["id"],
            }
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["formal_material_changed"] is True
    assert accepted.json()["manuscript_changed"] is False
    stored = accepted.json()["event"]
    assert stored["description"] == "门关上之后才开始"
    assert stored["event_time_text"] == "第4天"
    assert stored["chapter_id"] == chapter["id"]
    assert stored["certainty"] == "inferred"
    events = auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"]
    assert [item["description"] for item in events] == ["门关上之后才开始"]
    assert events[0]["participant_entity_ids"]

    again = auth_client.post(f"/api/v1/chronicle-candidates/{candidates[0]['id']}/accept", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TASK_STATE"

    rejected = auth_client.post(f"/api/v1/chronicle-candidates/{candidates[1]['id']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["formal_material_changed"] is False
    assert len(auth_client.get(f"/api/v1/novels/{novel['id']}/events").json()) == 1
    stored_chapter = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert stored_chapter["revision"] == chapter["revision"]

    other = _novel(auth_client, "隔壁")
    assert auth_client.get(f"/api/v1/novels/{other['id']}/chronicle/candidates").json() == []


def test_plan_uses_the_selected_model_config(auth_client: TestClient) -> None:
    seen: list[str] = []
    hints: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body.get("model")
        assert isinstance(model, str)
        seen.append(model)
        message = body.get("messages", [{}])[-1].get("content")
        if message == "ping":
            content = "pong"
        else:
            assert isinstance(message, str)
            assert SECRET not in message
            if "记住门" in message:
                hints.append(message)
            content = json.dumps(
                {
                    "events": [
                        {
                            "title": "模型排的事",
                            "description": "灯还没灭",
                            "event_time_text": "第2天",
                            "participants": ["阿禾"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"role": "assistant", "content": content}}],
            },
        )

    set_test_transport(httpx.MockTransport(handler))
    first = _model(auth_client, "甲", "model-a")
    second = _model(auth_client, "乙", "model-b")
    assert auth_client.post(f"/api/v1/settings/models/{first['id']}/test").status_code == 200
    assert auth_client.post(f"/api/v1/settings/models/{second['id']}/test").status_code == 200
    assert auth_client.put(f"/api/v1/settings/models/{first['id']}/default").status_code == 200
    novel = _novel(auth_client)
    seen.clear()

    missing = auth_client.post(
        f"/api/v1/novels/{_novel(auth_client, '空模型')['id']}/chronicle/plan",
        json={"use_mock": False},
    )
    # The default model exists, so this novel can plan. A novel with no configs is below.
    assert missing.status_code == 200, missing.text
    assert missing.json()["model_config_id"] == first["id"]
    assert seen == ["model-a"]
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"] == []

    bound = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chronicle/plan",
        json={"use_mock": True, "model_config_id": second["id"], "hint": "记住门"},
    )
    assert bound.status_code == 422
    assert bound.json()["error"]["code"] == "MODEL_CONFIG_INVALID"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle/candidates").json() == []

    picked = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chronicle/plan",
        json={"use_mock": False, "model_config_id": second["id"], "hint": "记住门"},
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["model_config_id"] == second["id"]
    assert picked.json()["formal_material_changed"] is False
    assert picked.json()["candidates"][0]["description"] == "灯还没灭"
    assert seen[-1] == "model-b"
    assert hints
    assert SECRET not in picked.text
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/events").json() == []


def test_plan_without_a_model_does_not_invent_events(auth_client: TestClient) -> None:
    novel = _novel(auth_client)
    response = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chronicle/plan",
        json={"use_mock": False},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle").json()["events"] == []
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/chronicle/candidates").json() == []


def test_package_roundtrip_keeps_chronicle_fields(auth_client: TestClient) -> None:
    novel, chapter = _novel_with_chapter(auth_client)
    character = _entity(auth_client, novel["id"], "character", "阿禾")
    created = _create(
        auth_client,
        novel["id"],
        description="亲手记下的入城",
        event_time_text="第3天",
        title="入城",
        participants=["阿禾"],
        chapter_id=str(chapter["id"]),
    )
    assert created["participant_entity_ids"] == [character["id"]]

    exported = auth_client.post(f"/api/v1/novels/{novel['id']}/portable-export")
    assert exported.status_code == 200, exported.text
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    memory = json.loads(archive.read("memory.json"))
    stored = memory["events"][0]
    assert stored["title"] == "入城"
    assert stored["event_time_text"] == "第3天"
    assert stored["participants"] == ["阿禾"]
    assert character["id"] in stored["participant_entity_ids"]

    imported = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("novel.zip", exported.content, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    copy_id = imported.json()["novel"]["id"]
    assert copy_id != novel["id"]
    copied = auth_client.get(f"/api/v1/novels/{copy_id}/chronicle").json()["events"]
    assert copied[0]["title"] == "入城"
    assert copied[0]["description"] == "亲手记下的入城"
    assert copied[0]["event_time_text"] == "第3天"
    assert copied[0]["participants"] == ["阿禾"]
    assert copied[0]["participant_entity_ids"]
    assert copied[0]["participant_entity_ids"] != [character["id"]]


def _novel(client: TestClient, title: str = "城门记") -> dict[str, object]:
    response = client.post("/api/v1/novels", json={"title": title})
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _novel_with_chapter(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    novel = _novel(client)
    created = client.post(f"/api/v1/novels/{novel['id']}/chapters", json={"title": "第一章"})
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/chapters/{created.json()['id']}",
        json={"revision": created.json()["revision"], "save_kind": "manual", "content": PARAGRAPH},
    )
    assert saved.status_code == 200, saved.text
    chapter = saved.json()
    assert isinstance(chapter, dict)
    return novel, chapter


def _entity(client: TestClient, novel_id: object, entity_type: str, name: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": entity_type, "name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _create(client: TestClient, novel_id: object, **payload: object) -> dict[str, object]:
    body = {"description": "一件事", **payload}
    response = client.post(f"/api/v1/novels/{novel_id}/events", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    assert isinstance(created, dict)
    return created


def _model(client: TestClient, name: str, model_name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/settings/models",
        json={
            "display_name": name,
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": model_name,
            "api_key": SECRET,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body
