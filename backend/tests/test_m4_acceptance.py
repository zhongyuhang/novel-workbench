"""M4 acceptance: T-012, T-013, stale memory, and novel isolation."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.services import memory as memory_service


def test_t012_reject_leaves_formal_memory_unchanged(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "审核作品", "林晚说道：“夜里城门已经关了。”疑似沈照。")
    analyzed = _analyze(auth_client, chapter)
    assert analyzed["provider_mode"] == "mock"
    assert analyzed["formal_memory_changed"] is False
    assert analyzed["manuscript_changed"] is False
    assert analyzed["proposal_count"] >= 1
    before = _memory_snapshot(auth_client, str(novel["id"]))
    assert before["entities"] == []
    assert before["events"] == []
    assert before["summaries"] == []

    for proposal in analyzed["proposals"]:
        rejected = auth_client.post(
            f"/api/v1/memory-proposals/{proposal['id']}/reject",
            json={},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

    after = _memory_snapshot(auth_client, str(novel["id"]))
    assert after["entities"] == []
    assert after["events"] == []
    assert after["summaries"] == []
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["revision"] == chapter["revision"]
    assert current.json()["content"] == chapter["content"]


def test_t013_accept_is_traceable_to_chapter_and_revision(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "来源作品", "林晚说道：“夜里城门已经关了。”")
    analyzed = _analyze(auth_client, chapter)
    proposal = next(
        item
        for item in analyzed["proposals"]
        if item["proposal_type"] == "entity_create" and item["payload"]["name"] == "林晚"
    )
    assert proposal["certainty"] == "confirmed"
    assert proposal["evidence_quote"]
    assert proposal["evidence_quote"] in "林晚说道：“夜里城门已经关了。”"
    assert proposal["source_chapter_id"] == chapter["id"]
    assert proposal["source_revision"] == chapter["revision"]

    accepted = auth_client.post(f"/api/v1/memory-proposals/{proposal['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["source_chapter_id"] == chapter["id"]
    assert body["source_revision"] == chapter["revision"]
    assert body["evidence_quote"] == proposal["evidence_quote"]

    entities = auth_client.get(f"/api/v1/novels/{novel['id']}/entities")
    assert entities.status_code == 200
    matched = [item for item in entities.json() if item["name"] == "林晚"]
    assert len(matched) == 1
    state = matched[0]["states"][0]
    assert state["chapter_id"] == chapter["id"]
    assert state["chapter_title"] == chapter["title"]
    assert state["source_revision"] == chapter["revision"]
    assert state["evidence_quote"] == proposal["evidence_quote"]
    assert state["source_type"] == "ai_proposal"
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["content"] == chapter["content"]
    assert current.json()["revision"] == chapter["revision"]


def test_uncertain_identity_does_not_become_a_formal_entity(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "猜测作品", "街上有人议论，疑似沈照。")
    analyzed = _analyze(auth_client, chapter)
    guessed = [
        item
        for item in analyzed["proposals"]
        if item["proposal_type"] == "entity_create" and item["payload"]["name"] == "沈照"
    ]
    assert guessed
    assert guessed[0]["certainty"] == "uncertain"
    assert guessed[0]["evidence_quote"] == ""
    entities = auth_client.get(f"/api/v1/novels/{novel['id']}/entities")
    assert entities.json() == []


def test_configured_model_without_evidence_stays_a_proposal(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "外部服务",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "demo-model",
            "api_key": "plain-secret-key-zz99",
        },
    )
    assert created.status_code == 201, created.text

    def fake_generate(**kwargs: object) -> str:
        assert kwargs["prompt"]
        return json.dumps(
            {
                "proposals": [
                    {
                        "proposal_type": "entity_create",
                        "certainty": "confirmed",
                        "evidence_quote": "我其实是皇子",
                        "payload": {
                            "entity_type": "character",
                            "name": "沈照",
                            "aliases": [],
                            "profile": {"summary": "无证据身份"},
                            "status": "active",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(memory_service, "generate_analysis_text", fake_generate)
    novel, chapter = _chapter(auth_client, "模型作品", "林晚说道：城门关了。")
    analyzed = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": False},
    )
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body["provider_mode"] == "openai_compatible"
    assert body["formal_memory_changed"] is False
    proposal = body["proposals"][0]
    assert proposal["certainty"] == "uncertain"
    assert proposal["evidence_in_source"] is False
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json() == []
    assert "plain-secret-key-zz99" not in analyzed.text


def test_revision_change_marks_summary_and_pending_proposal_stale(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "过期作品", "旧摘要标记甲。林晚说道：“你好。”")
    analyzed = _analyze(auth_client, chapter)
    summary = next(
        item for item in analyzed["proposals"] if item["proposal_type"] == "chapter_summary"
    )
    entity = next(
        item
        for item in analyzed["proposals"]
        if item["proposal_type"] == "entity_create" and item["payload"]["name"] == "林晚"
    )
    accepted = auth_client.post(f"/api/v1/memory-proposals/{summary['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text

    saved = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "save_kind": "manual",
            "content": _document("新正文。林晚说道：“你好。”"),
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == chapter["revision"] + 1

    summaries = auth_client.get(f"/api/v1/novels/{novel['id']}/chapter-summaries")
    assert summaries.status_code == 200
    assert summaries.json()[0]["status"] == "stale"
    assert summaries.json()[0]["source_revision"] == chapter["revision"]
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/memory-proposals")
    matched = next(item for item in listed.json() if item["id"] == entity["id"])
    assert matched["status"] == "stale"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json() == []


def test_memory_queries_do_not_leak_across_novels(auth_client: TestClient) -> None:
    first, first_chapter = _chapter(
        auth_client,
        "作品甲",
        "林晚说道：“只属于甲。”",
        style_guide="硬规则甲",
    )
    second, second_chapter = _chapter(auth_client, "作品乙", "这里没有林晚。")
    auth_client.post(
        f"/api/v1/novels/{second['id']}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "profile": {"summary": "乙书不应出现"},
            "status": "active",
        },
    )
    auth_client.post(
        f"/api/v1/novels/{first['id']}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "profile": {"summary": "左臂旧伤"},
            "status": "active",
        },
    )
    analyzed = _analyze(auth_client, first_chapter)
    proposal_ids = {item["id"] for item in analyzed["proposals"]}

    entities = auth_client.get(f"/api/v1/novels/{first['id']}/entities")
    assert [item["profile"]["summary"] for item in entities.json()] == ["左臂旧伤"]
    other_entities = auth_client.get(f"/api/v1/novels/{second['id']}/entities")
    assert [item["profile"]["summary"] for item in other_entities.json()] == ["乙书不应出现"]
    other_proposals = auth_client.get(f"/api/v1/novels/{second['id']}/memory-proposals")
    assert proposal_ids.isdisjoint({item["id"] for item in other_proposals.json()})
    assert auth_client.get(f"/api/v1/novels/{second['id']}/chapter-summaries").json() == []
    assert auth_client.get(f"/api/v1/novels/{second['id']}/events").json() == []

    task = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": first["id"],
            "chapter_id": first_chapter["id"],
            "task_type": "continue",
            "instruction": "顺着写",
            "target_revision": first_chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
        },
    )
    assert task.status_code == 201, task.text
    prompt = _task_prompt()
    assert "左臂旧伤" in prompt
    assert "硬规则甲" in prompt
    assert "乙书不应出现" not in prompt
    assert str(second_chapter["id"]) not in prompt


def test_context_uses_previous_chapter_and_ignores_other_novels(auth_client: TestClient) -> None:
    novel = auth_client.post(
        "/api/v1/novels",
        json={"title": "上下文", "style_guide": "硬规则甲"},
    ).json()
    other = auth_client.post("/api/v1/novels", json={"title": "另一本"}).json()
    previous = _save_new_chapter(auth_client, str(novel["id"]), "序章", "前文衔接甲")
    current = _save_new_chapter(auth_client, str(novel["id"]), "正文", "林晚说道：“继续走。”")
    auth_client.post(
        f"/api/v1/novels/{novel['id']}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "profile": {"summary": "左臂旧伤"},
            "status": "active",
        },
    )
    auth_client.post(
        f"/api/v1/novels/{other['id']}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "profile": {"summary": "乙书不应出现"},
            "status": "active",
        },
    )
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel["id"],
            "chapter_id": current["id"],
            "task_type": "continue",
            "instruction": "顺着写",
            "target_revision": current["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
        },
    )
    assert created.status_code == 201, created.text
    prompt = _task_prompt()
    assert "硬规则甲" in prompt
    assert "当前章节约束：正文" in prompt
    assert "前文衔接甲" in prompt
    assert "左臂旧伤" in prompt
    assert "乙书不应出现" not in prompt
    assert previous["id"] != current["id"]


def test_revert_removes_the_accepted_entity(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "撤回作品", "林晚说道：“夜里城门已经关了。”")
    analyzed = _analyze(auth_client, chapter)
    proposal = next(
        item
        for item in analyzed["proposals"]
        if item["proposal_type"] == "entity_create" and item["payload"]["name"] == "林晚"
    )
    accepted = auth_client.post(f"/api/v1/memory-proposals/{proposal['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    reverted = auth_client.post(f"/api/v1/memory-proposals/{proposal['id']}/revert", json={})
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "reverted"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json() == []


def test_memory_routes_cover_missing_invalid_and_anonymous(client: TestClient) -> None:
    denied = client.get("/api/v1/novels/missing/entities")
    assert denied.status_code == 401
    session = client.post("/api/v1/auth/session", json={"password": ""})
    assert session.status_code == 200, session.text
    client.headers["Authorization"] = f"Bearer {session.json()['access_token']}"
    missing = client.get("/api/v1/novels/missing-novel/entities")
    assert missing.status_code == 404
    novel, chapter = _chapter(client, "校验作品", "林晚说道：“在。”")
    invalid = client.post(
        f"/api/v1/novels/{novel['id']}/entities",
        json={"entity_type": "dragon", "name": "林晚"},
    )
    assert invalid.status_code == 422
    conflict = client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"] + 3, "use_mock": True},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"


def _chapter(
    client: TestClient,
    title: str,
    text: str,
    style_guide: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    payload: dict[str, object] = {"title": title}
    if style_guide is not None:
        payload["style_guide"] = style_guide
    novel = client.post("/api/v1/novels", json=payload).json()
    chapter = _save_new_chapter(client, str(novel["id"]), "第一章", text)
    return novel, chapter


def _save_new_chapter(
    client: TestClient, novel_id: str, title: str, text: str
) -> dict[str, object]:
    created = client.post(
        f"/api/v1/novels/{novel_id}/chapters",
        json={"title": title},
    )
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/chapters/{created.json()['id']}",
        json={
            "revision": created.json()["revision"],
            "save_kind": "manual",
            "content": _document(text),
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert isinstance(body, dict)
    return body


def _analyze(client: TestClient, chapter: dict[str, object]) -> dict[str, object]:
    response = client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _memory_snapshot(client: TestClient, novel_id: str) -> dict[str, list[object]]:
    entities = client.get(f"/api/v1/novels/{novel_id}/entities")
    events = client.get(f"/api/v1/novels/{novel_id}/events")
    summaries = client.get(f"/api/v1/novels/{novel_id}/chapter-summaries")
    assert entities.status_code == 200
    assert events.status_code == 200
    assert summaries.status_code == 200
    return {
        "entities": entities.json(),
        "events": events.json(),
        "summaries": summaries.json(),
    }


def _document(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _task_prompt() -> str:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT input_snapshot FROM ai_tasks ORDER BY created_at DESC")
        ).scalar_one()
    engine.dispose()
    snapshot = json.loads(stored) if isinstance(stored, str) else stored
    assert isinstance(snapshot, dict)
    prompt = snapshot["prompt"]
    assert isinstance(prompt, str)
    return prompt
