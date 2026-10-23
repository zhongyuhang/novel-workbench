"""Guided ideation stays a candidate until the author accepts it."""

import json
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


def test_ideation_requires_a_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/novels/missing/ideation/sessions",
        json={"kind": "guided", "use_mock": True},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_guided_candidates_do_not_write_until_accept(auth_client: TestClient) -> None:
    novel, chapter = _novel_with_chapter(auth_client, style_guide="旧文风")
    _entity(auth_client, novel["id"], "rule", "夜规")
    created = _start(auth_client, novel["id"], "guided")
    walked = _walk(
        auth_client,
        created,
        {
            "basis": "existing",
            "desire": "记住门关上的声音",
            "pressure": "有人被关在门外",
            "boundary": "不要写成轻松喜剧",
        },
    )
    assert walked["ready_to_generate"] is True

    generated = auth_client.post(f"/api/v1/ideation/sessions/{created['id']}/generate")
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["manuscript_changed"] is False
    assert body["formal_material_changed"] is False
    assert body["simulated"] is True
    assert body["provider_mode"] == "mock"
    assert SECRET not in generated.text
    candidates = body["session"]["candidates"]
    assert [item["title"] for item in candidates] == ["候选方向", "另一条方向"]
    assert "夜规" in candidates[0]["payload"]["synopsis"]
    assert candidates[0]["status"] == "pending"
    _assert_untouched(auth_client, novel, chapter, entity_names={"夜规"})
    assert auth_client.get(f"/api/v1/novels/{novel['id']}").json()["style_guide"] == "旧文风"

    deferred = auth_client.post(f"/api/v1/ideation-candidates/{candidates[0]['id']}/defer")
    rejected = auth_client.post(f"/api/v1/ideation-candidates/{candidates[1]['id']}/reject")
    assert deferred.status_code == 200, deferred.text
    assert rejected.status_code == 200, rejected.text
    assert deferred.json()["formal_material_changed"] is False
    assert rejected.json()["manuscript_changed"] is False
    _assert_untouched(auth_client, novel, chapter, entity_names={"夜规"})

    accepted = auth_client.post(
        f"/api/v1/ideation-candidates/{candidates[0]['id']}/accept",
        json={
            "payload": {
                "direction": "门外有人",
                "genre": "志怪",
                "core_conflict": "被关在门外",
                "synopsis": "短简介",
            }
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["formal_material_changed"] is True
    assert accepted.json()["manuscript_changed"] is False
    stored = auth_client.get(f"/api/v1/novels/{novel['id']}").json()
    assert stored["genre"] == "志怪"
    assert stored["core_conflict"] == "被关在门外"
    assert stored["synopsis"] == "短简介"
    assert stored["style_guide"] == "旧文风"
    plan = auth_client.get(f"/api/v1/novels/{novel['id']}/story-plan").json()["plan"]
    assert plan["logline"] == "门外有人"
    assert plan["status"] == "draft"
    assert plan["counts_as_fact"] is False
    _assert_chapter(auth_client, chapter)
    assert {item["name"] for item in _entities(auth_client, novel["id"])} == {"夜规"}

    again = auth_client.post(f"/api/v1/ideation-candidates/{candidates[0]['id']}/accept", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TASK_STATE"


def test_generate_before_answers_does_not_call_the_model(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"count": 0}

    def explode(*args: object, **kwargs: object) -> str:
        called["count"] += 1
        raise AssertionError("model should not be called")

    monkeypatch.setattr("app.services.ideation.generate_analysis_text", explode)
    novel = _novel(auth_client)
    created = _start(auth_client, novel["id"], "guided")
    answered = auth_client.post(
        f"/api/v1/ideation/sessions/{created['id']}/answers",
        json={"question_id": "basis", "answer": "scratch"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["ready_to_generate"] is False

    generated = auth_client.post(f"/api/v1/ideation/sessions/{created['id']}/generate")
    assert generated.status_code == 422
    assert called["count"] == 0
    assert (
        auth_client.get(f"/api/v1/novels/{novel['id']}/ideation/sessions").json()[0]["candidates"]
        == []
    )


def test_world_and_character_candidates_write_only_after_accept(auth_client: TestClient) -> None:
    novel, chapter = _novel_with_chapter(auth_client)
    _entity(auth_client, novel["id"], "character", "阿禾")
    world = _start(auth_client, novel["id"], "world")
    _walk(auth_client, world, {"focus": "rule", "hint": "城门夜里不能开"})
    generated = auth_client.post(f"/api/v1/ideation/sessions/{world['id']}/generate")
    assert generated.status_code == 200, generated.text
    candidate = generated.json()["session"]["candidates"][0]
    assert candidate["payload"]["entity_type"] == "rule"
    assert candidate["payload"]["name"] == "夜禁"
    assert "阿禾" in candidate["payload"]["summary"]
    assert "城门夜里不能开" in candidate["payload"]["summary"]
    assert {item["name"] for item in _entities(auth_client, novel["id"])} == {"阿禾"}

    duplicate = _entity(auth_client, novel["id"], "rule", "夜禁")
    blocked = auth_client.post(f"/api/v1/ideation-candidates/{candidate['id']}/accept", json={})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DUPLICATE_ENTITY"
    assert {item["name"] for item in _entities(auth_client, novel["id"])} == {"阿禾", "夜禁"}
    still = auth_client.get(f"/api/v1/ideation/sessions/{world['id']}")
    assert still.json()["candidates"][0]["status"] == "pending"
    renamed = auth_client.patch(
        f"/api/v1/entities/{duplicate['id']}",
        json={"name": "旧夜禁"},
    )
    assert renamed.status_code == 200, renamed.text
    accepted = auth_client.post(f"/api/v1/ideation-candidates/{candidate['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    names = {item["name"] for item in _entities(auth_client, novel["id"])}
    assert "夜禁" in names
    assert "阿禾" in names

    character = _start(auth_client, novel["id"], "character")
    _walk(auth_client, character, {"focus": "protagonist", "hint": "不要让他先认输"})
    designed = auth_client.post(f"/api/v1/ideation/sessions/{character['id']}/generate")
    assert designed.status_code == 200, designed.text
    by_kind = {item["candidate_kind"]: item for item in designed.json()["session"]["candidates"]}
    relation = by_kind["character_relation"]
    assert relation["payload"]["to_name"] == "阿禾"
    too_soon = auth_client.post(f"/api/v1/ideation-candidates/{relation['id']}/accept", json={})
    assert too_soon.status_code == 422
    assert "夜禁" in names
    assert "沈酌" not in {item["name"] for item in _entities(auth_client, novel["id"])}

    card = auth_client.post(
        f"/api/v1/ideation-candidates/{by_kind['character_card']['id']}/accept",
        json={},
    )
    assert card.status_code == 200, card.text
    linked = auth_client.post(f"/api/v1/ideation-candidates/{relation['id']}/accept", json={})
    assert linked.status_code == 200, linked.text
    relations = auth_client.get(f"/api/v1/novels/{novel['id']}/relations").json()
    assert relations[0]["relation_type"] == "亏欠"
    arc = auth_client.post(
        f"/api/v1/ideation-candidates/{by_kind['character_arc']['id']}/accept",
        json={},
    )
    assert arc.status_code == 200, arc.text
    arcs = auth_client.get(f"/api/v1/novels/{novel['id']}/story-arcs").json()
    stored_arc = arcs[0]
    assert stored_arc["arc_type"] == "character"
    assert stored_arc["status"] == "draft"
    assert stored_arc["counts_as_fact"] is False
    _assert_chapter(auth_client, chapter)


def test_model_config_is_fixed_for_the_session(auth_client: TestClient) -> None:
    seen: list[str] = []

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
            assert "记住门" in message
            assert SECRET not in message
            content = json.dumps(
                {
                    "candidates": [
                        {
                            "kind": "work_direction",
                            "title": "模型方向",
                            "payload": {
                                "direction": "门后还有一盏灯",
                                "genre": "志怪",
                                "tone": "短句",
                                "core_conflict": "灯灭之前要做出选择",
                                "synopsis": "一个人在门外等灯。",
                            },
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

    defaulted = _start(auth_client, novel["id"], "guided", use_mock=False)
    assert defaulted["model_config_id"] == first["id"]
    assert defaulted["provider_mode"] == "openai_compatible"
    _walk(
        auth_client,
        defaulted,
        {
            "basis": "scratch",
            "desire": "记住门",
            "pressure": "灯还没灭",
            "boundary": "不要解释结局",
        },
    )
    generated = auth_client.post(f"/api/v1/ideation/sessions/{defaulted['id']}/generate")
    assert generated.status_code == 200, generated.text
    assert generated.json()["model_config_id"] == first["id"]
    assert generated.json()["formal_material_changed"] is False
    assert seen == ["model-a"]
    assert auth_client.get(f"/api/v1/novels/{novel['id']}").json()["genre"] is None
    assert SECRET not in generated.text

    bound = auth_client.post(
        f"/api/v1/novels/{novel['id']}/ideation/sessions",
        json={"kind": "guided", "use_mock": True, "model_config_id": second["id"]},
    )
    assert bound.status_code == 422
    assert bound.json()["error"]["code"] == "MODEL_CONFIG_INVALID"

    picked = _start(
        auth_client,
        novel["id"],
        "guided",
        use_mock=False,
        model_config_id=second["id"],
    )
    assert picked["model_config_id"] == second["id"]
    _walk(
        auth_client,
        picked,
        {
            "basis": "scratch",
            "desire": "记住门",
            "pressure": "灯还没灭",
            "boundary": "不要解释结局",
        },
    )
    second_run = auth_client.post(f"/api/v1/ideation/sessions/{picked['id']}/generate")
    assert second_run.status_code == 200, second_run.text
    assert seen[-1] == "model-b"
    again = auth_client.post(f"/api/v1/ideation/sessions/{defaulted['id']}/generate")
    assert again.status_code == 200, again.text
    assert seen[-1] == "model-a"


def test_missing_model_does_not_invent_a_session(auth_client: TestClient) -> None:
    novel = _novel(auth_client)
    response = auth_client.post(
        f"/api/v1/novels/{novel['id']}/ideation/sessions",
        json={"kind": "world", "use_mock": False},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/ideation/sessions").json() == []


def test_sessions_stay_inside_the_novel(auth_client: TestClient) -> None:
    first = _novel(auth_client, title="甲书")
    second = _novel(auth_client, title="乙书")
    created = _start(auth_client, first["id"], "guided")

    isolated = auth_client.get(f"/api/v1/novels/{second['id']}/ideation/sessions")
    assert isolated.status_code == 200
    assert isolated.json() == []
    assert auth_client.get(f"/api/v1/novels/{second['id']}").json()["genre"] is None
    assert created["novel_id"] == first["id"]


def _novel(client: TestClient, title: str = "城门记") -> dict[str, object]:
    response = client.post("/api/v1/novels", json={"title": title})
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _novel_with_chapter(
    client: TestClient,
    *,
    style_guide: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    payload: dict[str, object] = {"title": "城门记"}
    if style_guide is not None:
        payload["style_guide"] = style_guide
    novel = client.post("/api/v1/novels", json=payload)
    assert novel.status_code == 201, novel.text
    novel_body = novel.json()
    created = client.post(
        f"/api/v1/novels/{novel_body['id']}/chapters",
        json={"title": "第一章"},
    )
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/chapters/{created.json()['id']}",
        json={
            "revision": created.json()["revision"],
            "save_kind": "manual",
            "content": PARAGRAPH,
        },
    )
    assert saved.status_code == 200, saved.text
    assert isinstance(novel_body, dict)
    chapter = saved.json()
    assert isinstance(chapter, dict)
    return novel_body, chapter


def _entity(client: TestClient, novel_id: object, entity_type: str, name: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": entity_type, "name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _entities(client: TestClient, novel_id: object) -> list[dict[str, object]]:
    response = client.get(f"/api/v1/novels/{novel_id}/entities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return [item for item in body if isinstance(item, dict)]


def _start(
    client: TestClient,
    novel_id: object,
    kind: str,
    *,
    use_mock: bool = True,
    model_config_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"kind": kind, "use_mock": use_mock}
    if model_config_id is not None:
        payload["model_config_id"] = model_config_id
    response = client.post(f"/api/v1/novels/{novel_id}/ideation/sessions", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _walk(
    client: TestClient,
    current: dict[str, object],
    answers: dict[str, str],
) -> dict[str, object]:
    for _ in range(6):
        question = current.get("current_question")
        if not isinstance(question, dict):
            break
        question_id = question["id"]
        assert isinstance(question_id, str)
        response = client.post(
            f"/api/v1/ideation/sessions/{current['id']}/answers",
            json={"question_id": question_id, "answer": answers.get(question_id, "")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body, dict)
        current = body
    assert current["ready_to_generate"] is True
    return current


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


def _assert_untouched(
    client: TestClient,
    novel: dict[str, object],
    chapter: dict[str, object],
    *,
    entity_names: set[str],
) -> None:
    stored = client.get(f"/api/v1/novels/{novel['id']}").json()
    assert stored["genre"] == novel["genre"]
    assert stored["synopsis"] == novel["synopsis"]
    assert stored["core_conflict"] == novel["core_conflict"]
    assert {item["name"] for item in _entities(client, novel["id"])} == entity_names
    _assert_chapter(client, chapter)


def _assert_chapter(client: TestClient, chapter: dict[str, object]) -> None:
    current = client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert current["revision"] == chapter["revision"]
    assert current["content"] == chapter["content"]
    assert current["word_count"] == chapter["word_count"]
