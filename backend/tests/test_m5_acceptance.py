"""M5: foreshadowing, suspected conflicts, selection rewrite, and stats."""

import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.content import document_to_text, text_to_document, word_count
from app.services.conflicts import ConfirmedFact, find_suspected_conflicts


def test_foreshadowing_is_isolated_and_status_can_change(auth_client: TestClient) -> None:
    first = _novel(auth_client, "甲本")
    second = _novel(auth_client, "乙本")
    chapter = _chapter(auth_client, first, "埋下")
    other = _chapter(auth_client, second, "另一本")
    payoff = _chapter(auth_client, first, "回收")

    created = auth_client.post(
        f"/api/v1/novels/{first}/foreshadowing",
        json={
            "introduced_chapter_id": chapter,
            "description": "抽屉里的钥匙",
            "status": "open",
            "evidence_quote": "钥匙还在抽屉里",
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["novel_id"] == first
    assert item["status"] == "open"

    leaked = auth_client.post(
        f"/api/v1/novels/{first}/foreshadowing",
        json={"introduced_chapter_id": other, "description": "不该写入"},
    )
    assert leaked.status_code == 422
    assert leaked.json()["error"]["code"] == "INVALID_REFERENCE"

    hidden = auth_client.get(f"/api/v1/novels/{second}/foreshadowing")
    assert hidden.status_code == 200
    assert hidden.json() == []

    listed = auth_client.get(f"/api/v1/novels/{first}/foreshadowing")
    assert [row["id"] for row in listed.json()] == [item["id"]]

    current = item
    for status_name in ("planned", "resolved", "abandoned", "uncertain", "open"):
        patched = auth_client.patch(
            f"/api/v1/foreshadowing/{item['id']}",
            json={
                "status": status_name,
                "payoff_chapter_id": payoff,
                "description": "抽屉里的旧钥匙",
            },
        )
        assert patched.status_code == 200, patched.text
        current = patched.json()
        assert current["status"] == status_name
        assert current["payoff_chapter_id"] == payoff
        assert current["description"] == "抽屉里的旧钥匙"

    cleared = auth_client.patch(
        f"/api/v1/foreshadowing/{item['id']}",
        json={"payoff_chapter_id": None, "evidence_quote": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["payoff_chapter_id"] is None
    assert cleared.json()["evidence_quote"] is None
    assert cleared.json()["status"] == current["status"]

    wrong_payoff = auth_client.patch(
        f"/api/v1/foreshadowing/{item['id']}",
        json={"payoff_chapter_id": other},
    )
    assert wrong_payoff.status_code == 422

    filtered = auth_client.get(f"/api/v1/novels/{first}/foreshadowing", params={"status": "open"})
    assert [row["id"] for row in filtered.json()] == [item["id"]]
    planned = auth_client.get(
        f"/api/v1/novels/{first}/foreshadowing",
        params={"status": "planned"},
    )
    assert planned.json() == []

    missing = auth_client.patch("/api/v1/foreshadowing/missing", json={"status": "open"})
    assert missing.status_code == 404
    invalid = auth_client.post(
        f"/api/v1/novels/{first}/foreshadowing",
        json={"introduced_chapter_id": chapter, "description": "x", "status": "done"},
    )
    assert invalid.status_code == 422


def test_conflict_check_returns_hints_without_writing(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("conflict mock path tried to open a network client")

    monkeypatch.setattr(httpx, "Client", explode)
    novel = _novel(auth_client, "冲突")
    source = _save(auth_client, _chapter(auth_client, novel, "前文"), "阿宁是左撇子。")
    current = _save(
        auth_client,
        _chapter(auth_client, novel, "后文"),
        "阿宁是右撇子。阿宁不是左撇子。阿宁来到江南。",
    )
    entity = auth_client.post(
        f"/api/v1/novels/{novel}/entities",
        json={"entity_type": "character", "name": "阿宁", "profile": {"summary": "人物"}},
    )
    assert entity.status_code == 201, entity.text
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
        certainty="confirmed",
    )
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="阿宁是蓝眼睛",
        quote="阿宁是蓝眼睛",
        certainty="inferred",
    )
    _insert_state(entity.json()["id"], current, {"location": "江南"})
    hint = auth_client.post(
        f"/api/v1/novels/{novel}/foreshadowing",
        json={"introduced_chapter_id": source, "description": "左撇子的习惯"},
    )
    assert hint.status_code == 201, hint.text

    before = _memory_snapshot(auth_client, novel, [source, current])
    checked = auth_client.post(
        f"/api/v1/chapters/{current}/conflict-check",
        json={"use_mock": True},
    )
    assert checked.status_code == 200, checked.text
    after = _memory_snapshot(auth_client, novel, [source, current])
    assert after == before

    body = checked.json()
    assert body["provider_mode"] == "mock"
    assert body["manuscript_changed"] is False
    assert body["formal_memory_changed"] is False
    assert body["prompt_version"] == "conflict_check_v1"
    kinds = {item["conflict_type"] for item in body["conflicts"]}
    assert kinds == {"attribute_contradiction", "negated_fact"}
    for item in body["conflicts"]:
        assert item["confirmed_fact"] == "阿宁是左撇子"
        assert item["source_quote"] == "阿宁是左撇子"
        assert item["source_chapter_id"] == source
        assert item["source_chapter_title"] == "前文"
        assert item["manuscript_snippet"]
        assert item["severity"] in {"low", "medium", "high"}
        assert 0 <= item["confidence"] <= 1
        assert "不会自动修改正文或正式记忆" in item["suggested_action"]
        assert "江南" not in item["manuscript_snippet"]
    negated = next(item for item in body["conflicts"] if item["conflict_type"] == "negated_fact")
    assert negated["severity"] == "high"
    assert "不是左撇子" in negated["manuscript_snippet"]

    same = auth_client.post(f"/api/v1/chapters/{source}/conflict-check", json={})
    assert same.status_code == 200, same.text
    assert same.json()["conflicts"] == []
    assert _memory_snapshot(auth_client, novel, [source, current]) == before


def test_entity_state_change_alone_is_not_a_conflict(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "状态")
    chapter = _save(auth_client, _chapter(auth_client, novel, "赶路"), "阿宁离开了京城，来到江南。")
    entity = auth_client.post(
        f"/api/v1/novels/{novel}/entities",
        json={"entity_type": "character", "name": "阿宁"},
    )
    assert entity.status_code == 201, entity.text
    _insert_state(entity.json()["id"], chapter, {"location": "京城"})
    _insert_state(entity.json()["id"], chapter, {"location": "江南"})

    checked = auth_client.post(
        f"/api/v1/chapters/{chapter}/conflict-check",
        json={"use_mock": True},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["conflicts"] == []
    assert checked.json()["formal_memory_changed"] is False


def test_model_conflict_hints_are_filtered_and_do_not_write(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel = _novel(auth_client, "模型冲突")
    source = _save(auth_client, _chapter(auth_client, novel, "设定"), "城门是关着的。")
    current = _save(auth_client, _chapter(auth_client, novel, "正文"), "城门是开着的。")
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="城门是关着的",
        quote="城门是关着的",
        certainty="confirmed",
    )
    config = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "外部",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "demo",
            "api_key": "sk-test-secret",
            "timeout_seconds": 5,
        },
    )
    assert config.status_code == 201, config.text

    def fake_generate(**_kwargs: object) -> str:
        return json.dumps(
            {
                "conflicts": [
                    {
                        "conflict_type": "attribute_contradiction",
                        "manuscript_snippet": "城门是开着的。",
                        "source_quote": "城门是关着的",
                        "severity": "medium",
                        "confidence": 0.6,
                        "suggested_action": "请人工看一眼",
                    },
                    {
                        "conflict_type": "attribute_contradiction",
                        "manuscript_snippet": "这段不在正文里",
                        "source_quote": "城门是关着的",
                        "severity": "high",
                        "confidence": 0.9,
                        "suggested_action": "丢掉",
                    },
                    {
                        "conflict_type": "negated_fact",
                        "manuscript_snippet": "城门是开着的。",
                        "source_quote": "模型编造的事实",
                        "severity": "high",
                        "confidence": 0.9,
                        "suggested_action": "丢掉",
                    },
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.conflicts.generate_conflict_text", fake_generate)
    before = _memory_snapshot(auth_client, novel, [source, current])
    checked = auth_client.post(
        f"/api/v1/chapters/{current}/conflict-check",
        json={"use_mock": False, "model_config_id": config.json()["id"]},
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["provider_mode"] == "openai_compatible"
    assert body["manuscript_changed"] is False
    assert body["formal_memory_changed"] is False
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["confirmed_fact"] == "城门是关着的"
    action = body["conflicts"][0]["suggested_action"]
    assert isinstance(action, str)
    assert "不会自动修改" in action
    assert _memory_snapshot(auth_client, novel, [source, current]) == before

    def bad_generate(**_kwargs: object) -> str:
        return "不是 JSON"

    monkeypatch.setattr("app.services.conflicts.generate_conflict_text", bad_generate)
    failed = auth_client.post(
        f"/api/v1/chapters/{current}/conflict-check",
        json={"use_mock": False, "model_config_id": config.json()["id"]},
    )
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "MODEL_BAD_RESPONSE"
    assert "sk-test-secret" not in failed.text
    assert _memory_snapshot(auth_client, novel, [source, current]) == before


def test_no_model_still_uses_the_mock_conflict_path(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "无模型")
    chapter = _save(auth_client, _chapter(auth_client, novel, "空"), "什么都没有发生。")
    checked = auth_client.post(
        f"/api/v1/chapters/{chapter}/conflict-check",
        json={"use_mock": False},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["provider_mode"] == "mock"
    assert checked.json()["conflicts"] == []
    assert checked.json()["manuscript_changed"] is False


def test_selection_rewrite_stays_a_candidate_until_accept(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "改写")
    chapter_id = _chapter(auth_client, novel, "门口")
    chapter = _put(auth_client, chapter_id, 1, "甲段保留。乙段要改。")
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel,
            "chapter_id": chapter_id,
            "task_type": "rewrite",
            "instruction": "把后半句写慢一点",
            "selection_text": "乙段要改。",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["乙段已改。"],
        },
    )
    assert created.status_code == 201, created.text
    task = _wait(auth_client, created.json()["id"])
    assert task["status"] == "completed"
    assert task["prompt_version"] == "rewrite_selection_v1"
    assert task["resolution"] is None
    assert task["output_text"] == "乙段已改。"
    assert _chapter_body(auth_client, chapter_id) == "甲段保留。乙段要改。"

    rejected = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel,
            "chapter_id": chapter_id,
            "task_type": "rewrite",
            "instruction": "不要写入",
            "selection_text": "乙段要改。",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["不该留下。"],
        },
    )
    rejected_task = _wait(auth_client, rejected.json()["id"])
    stale_created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel,
            "chapter_id": chapter_id,
            "task_type": "rewrite",
            "instruction": "过期候选",
            "selection_text": "乙段要改。",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["过期改写。"],
        },
    )
    stale_task = _wait(auth_client, stale_created.json()["id"])
    refused = auth_client.post(f"/api/v1/ai/tasks/{rejected_task['id']}/reject")
    assert refused.status_code == 200, refused.text
    assert refused.json()["resolution"] == "rejected"
    assert _chapter_body(auth_client, chapter_id) == "甲段保留。乙段要改。"

    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "replace_selection"},
    )
    assert accepted.status_code == 200, accepted.text
    saved = accepted.json()["chapter"]
    assert document_to_text(saved["content"]) == "甲段保留。乙段已改。"
    assert saved["revision"] == chapter["revision"] + 1
    assert accepted.json()["task"]["resolution"] == "accepted"

    stale = auth_client.post(
        f"/api/v1/ai/tasks/{stale_task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "replace_selection"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    current = auth_client.get(f"/api/v1/chapters/{chapter_id}")
    assert current.json()["revision"] == saved["revision"]
    assert document_to_text(current.json()["content"]) == "甲段保留。乙段已改。"


def test_rewrite_without_selection_keeps_general_prompt(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "整章改写")
    chapter_id = _chapter(auth_client, novel, "一章")
    chapter = _put(auth_client, chapter_id, 1, "原句。")
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel,
            "chapter_id": chapter_id,
            "task_type": "rewrite",
            "instruction": "改得更短",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["短句。"],
        },
    )
    task = _wait(auth_client, created.json()["id"])
    assert task["prompt_version"] == "m4.v1"
    assert _chapter_body(auth_client, chapter_id) == "原句。"


def test_stats_use_the_word_count_helper(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "统计")
    first_doc = text_to_document("甲乙丙")
    second_doc = text_to_document("丁 戊")
    first = _chapter(auth_client, novel, "一")
    second = _chapter(auth_client, novel, "二")
    _put_document(auth_client, first, 1, first_doc)
    _put_document(auth_client, second, 1, second_doc)
    expected_first = word_count(first_doc)
    expected_second = word_count(second_doc)

    stats = auth_client.get(f"/api/v1/novels/{novel}/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["target_words"] is None
    assert body["chapter_count"] == 2
    counts = {item["title"]: item["word_count"] for item in body["chapters"]}
    assert counts == {"一": expected_first, "二": expected_second}
    assert body["total_word_count"] == expected_first + expected_second
    assert expected_first == 3
    assert expected_second == 2

    goal = auth_client.put(f"/api/v1/novels/{novel}/writing-goal", json={"target_words": 1000})
    assert goal.status_code == 200, goal.text
    assert goal.json()["target_words"] == 1000
    assert goal.json()["total_word_count"] == expected_first + expected_second
    again = auth_client.get(f"/api/v1/novels/{novel}/stats")
    assert again.json()["target_words"] == 1000
    stored = auth_client.get(f"/api/v1/chapters/{first}")
    assert document_to_text(stored.json()["content"]) == "甲乙丙"


def test_quality_routes_require_a_session(client: TestClient) -> None:
    listing = client.get("/api/v1/novels/x/foreshadowing")
    stats = client.get("/api/v1/novels/x/stats")
    checked = client.post("/api/v1/chapters/x/conflict-check", json={})
    assert listing.status_code == 401
    assert stats.status_code == 401
    assert checked.status_code == 401
    assert listing.json()["error"]["code"] == "UNAUTHENTICATED"


def test_local_rules_ignore_matching_claims() -> None:
    fact = ConfirmedFact("阿宁是左撇子", "chapter-1", "阿宁是左撇子")
    assert find_suspected_conflicts("阿宁是左撇子。", [fact]) == []
    assert find_suspected_conflicts("阿宁来到江南。", [fact]) == []
    found = find_suspected_conflicts("阿宁的眼睛是黑色。", [fact])
    assert found == []


def _novel(client: TestClient, title: str) -> str:
    response = client.post("/api/v1/novels", json={"title": title})
    assert response.status_code == 201, response.text
    novel_id = response.json()["id"]
    assert isinstance(novel_id, str)
    return novel_id


def _chapter(client: TestClient, novel_id: str, title: str) -> str:
    response = client.post(f"/api/v1/novels/{novel_id}/chapters", json={"title": title})
    assert response.status_code == 201, response.text
    chapter_id = response.json()["id"]
    assert isinstance(chapter_id, str)
    return chapter_id


def _save(client: TestClient, chapter_id: str, text_value: str) -> str:
    saved = _put(client, chapter_id, 1, text_value)
    assert saved["id"] == chapter_id
    return chapter_id


def _put(client: TestClient, chapter_id: str, revision: int, text_value: str) -> dict[str, object]:
    return _put_document(client, chapter_id, revision, text_to_document(text_value))


def _put_document(
    client: TestClient,
    chapter_id: str,
    revision: int,
    document: dict[str, object],
) -> dict[str, object]:
    response = client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={"revision": revision, "save_kind": "manual", "content": document},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _chapter_body(client: TestClient, chapter_id: str) -> str:
    response = client.get(f"/api/v1/chapters/{chapter_id}")
    assert response.status_code == 200, response.text
    return document_to_text(response.json()["content"])


def _memory_snapshot(
    client: TestClient,
    novel_id: str,
    chapter_ids: list[str],
) -> dict[str, object]:
    chapters = []
    for chapter_id in chapter_ids:
        response = client.get(f"/api/v1/chapters/{chapter_id}")
        assert response.status_code == 200, response.text
        chapters.append(response.json())
    entities = client.get(f"/api/v1/novels/{novel_id}/entities")
    events = client.get(f"/api/v1/novels/{novel_id}/events")
    proposals = client.get(f"/api/v1/novels/{novel_id}/memory-proposals")
    foreshadowing = client.get(f"/api/v1/novels/{novel_id}/foreshadowing")
    assert entities.status_code == 200
    assert events.status_code == 200
    assert proposals.status_code == 200
    assert foreshadowing.status_code == 200
    return {
        "chapters": chapters,
        "entities": entities.json(),
        "events": events.json(),
        "proposals": proposals.json(),
        "foreshadowing": foreshadowing.json(),
    }


def _insert_event(
    *,
    novel_id: str,
    chapter_id: str,
    description: str,
    quote: str,
    certainty: str,
) -> None:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO story_events (
                    id, novel_id, chapter_id, source_revision, proposal_id,
                    event_time_text, description, participants, evidence_quote,
                    certainty, created_at, deleted_at
                ) VALUES (
                    :id, :novel_id, :chapter_id, 1, NULL,
                    NULL, :description, '[]', :quote,
                    :certainty, '2026-01-01 00:00:00', NULL
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "novel_id": novel_id,
                "chapter_id": chapter_id,
                "description": description,
                "quote": quote,
                "certainty": certainty,
            },
        )
    engine.dispose()


def _insert_state(entity_id: str, chapter_id: str, state: dict[str, str]) -> None:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO entity_states (
                    id, entity_id, chapter_id, source_revision, proposal_id,
                    state_data, evidence_quote, source_type, created_at
                ) VALUES (
                    :id, :entity_id, :chapter_id, 1, NULL,
                    :state_data, NULL, 'manual', '2026-01-01 00:00:00'
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "chapter_id": chapter_id,
                "state_data": json.dumps(state, ensure_ascii=False),
            },
        )
    engine.dispose()


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
