"""Persisted quality issues, repair preview, and revision-checked accept."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.content import document_to_text, text_to_document
from app.services import quality_issues as issue_service


def test_quality_routes_require_session(client: TestClient) -> None:
    checked = client.post("/api/v1/novels/missing/quality-check", json={})
    listing = client.get("/api/v1/novels/missing/quality-issues")

    assert checked.status_code == 401
    assert listing.status_code == 401
    assert checked.json()["error"]["code"] == "UNAUTHENTICATED"


def test_rule_check_stores_evidence_and_does_not_write(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rule check tried to call a model")

    monkeypatch.setattr(issue_service, "generate_conflict_text", explode)
    monkeypatch.setattr(httpx, "Client", explode)
    novel = _novel(auth_client, "质量")
    source = _save(auth_client, _chapter(auth_client, novel, "前文"), "阿宁是左撇子。")
    current = _save(auth_client, _chapter(auth_client, novel, "后文"), "阿宁是右撇子。")
    other = _novel(auth_client, "另一本")
    _save(auth_client, _chapter(auth_client, other, "无关"), "阿宁是右撇子。")
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
    )
    before = _snapshot(auth_client, novel, [source, current])

    checked = auth_client.post(
        f"/api/v1/novels/{novel}/quality-check",
        json={"use_model": False},
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["manuscript_changed"] is False
    assert body["formal_memory_changed"] is False
    assert body["provider_mode"] == "rule"
    assert body["rule_version"] == "quality_rules_v1"
    assert body["analysis_version"] is None
    assert "模型检查未启用" in body["message"]
    assert _snapshot(auth_client, novel, [source, current]) == before

    issues = body["issues"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["issue_type"] == "fact_continuity"
    assert issue["status"] == "pending"
    assert issue["evidence_status"] == "sufficient"
    assert issue["manuscript_snippet"]
    assert issue["target_revision"]
    assert "offset" not in issue
    assert issue["evidence"]
    assert issue["evidence"][1]["quote"] == "阿宁是左撇子"
    assert issue["evidence"][1]["source_chapter_id"] == source
    assert issue["related_refs"]
    assert "不会自动修改正文或正式记忆" in issue["suggested_action"]
    assert issue["chapter_id"] == current

    again = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert again.status_code == 200, again.text
    assert [item["id"] for item in again.json()["issues"]] == [issue["id"]]
    isolated = auth_client.post(f"/api/v1/novels/{other}/quality-check", json={})
    assert isolated.status_code == 200, isolated.text
    assert isolated.json()["issues"] == []
    hidden = auth_client.get(f"/api/v1/novels/{other}/quality-issues")
    assert hidden.status_code == 200, hidden.text
    assert hidden.json() == []


def test_state_change_without_validity_is_not_stored(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "状态")
    chapter = _save(auth_client, _chapter(auth_client, novel, "赶路"), "阿宁来到江南。")
    entity = auth_client.post(
        f"/api/v1/novels/{novel}/entities",
        json={"entity_type": "character", "name": "阿宁"},
    )
    assert entity.status_code == 201, entity.text
    for place in ("京城", "江南"):
        created = auth_client.post(
            f"/api/v1/entities/{entity.json()['id']}/states",
            json={"chapter_id": chapter, "state_data": {"location": place}},
        )
        assert created.status_code == 201, created.text

    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    assert checked.json()["issues"] == []


def test_overlapping_validity_is_stored_as_suspected_time_issue(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "时间")
    earlier = _save(auth_client, _chapter(auth_client, novel, "春"), "人在京城。")
    later = _save(auth_client, _chapter(auth_client, novel, "夏"), "人在江南。")
    entity = auth_client.post(
        f"/api/v1/novels/{novel}/entities",
        json={"entity_type": "character", "name": "阿宁"},
    )
    assert entity.status_code == 201, entity.text
    for chapter_id, place in ((earlier, "京城"), (later, "江南")):
        created = auth_client.post(
            f"/api/v1/entities/{entity.json()['id']}/states",
            json={
                "chapter_id": chapter_id,
                "state_data": {"location": place},
                "evidence_quote": f"人在{place}",
                "valid_from_text": "第1天",
                "valid_until_text": "第5天",
            },
        )
        assert created.status_code == 201, created.text

    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    issues = checked.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "time_continuity"
    assert issues[0]["evidence_status"] == "sufficient"
    assert len(issues[0]["related_refs"]) == 2


def test_outline_draft_is_ignored_until_confirmed(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "大纲")
    chapter = _save(auth_client, _chapter(auth_client, novel, "本章"), "他终于说出铜钥匙在井里。")
    drafted = auth_client.put(
        f"/api/v1/chapters/{chapter}/outline",
        json={"forbidden_reveals": "铜钥匙在井里"},
    )
    assert drafted.status_code == 200, drafted.text
    quiet = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert quiet.status_code == 200, quiet.text
    assert quiet.json()["issues"] == []

    confirmed = auth_client.post(
        f"/api/v1/chapters/{chapter}/outline/confirm",
        json={"expected_revision": drafted.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    issues = checked.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["rule_id"] == "outline.forbidden_leak"
    assert "铜钥匙在井里" in issues[0]["manuscript_snippet"]


def test_repair_preview_accept_conflict_and_recheck(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "修复")
    source = _save(auth_client, _chapter(auth_client, novel, "前文"), "阿宁是左撇子。")
    current = _chapter(auth_client, novel, "后文")
    saved = _put(auth_client, current, 1, "阿宁是右撇子。")
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
    )
    entities_before = auth_client.get(f"/api/v1/novels/{novel}/entities")
    events_before = auth_client.get(f"/api/v1/novels/{novel}/events")
    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={"use_model": False})
    assert checked.status_code == 200, checked.text
    issue = checked.json()["issues"][0]

    suggested = auth_client.post(f"/api/v1/quality-issues/{issue['id']}/repairs", json={})
    assert suggested.status_code == 200, suggested.text
    assert suggested.json()["manuscript_changed"] is False
    assert suggested.json()["formal_memory_changed"] is False
    candidate = suggested.json()["candidates"][0]
    assert candidate["applicable"] is True
    assert candidate["status"] == "proposed"
    assert "当前正文" in candidate["diff_preview"]
    assert "阿宁是右撇子。" in candidate["diff_preview"]
    assert "阿宁是左撇子" in candidate["diff_preview"]
    assert "不会自动修改正文或正式记忆" in candidate["rationale"]
    assert _revision(auth_client, current) == saved["revision"]

    conflicted = auth_client.put(
        f"/api/v1/chapters/{current}",
        json={
            "revision": saved["revision"],
            "save_kind": "manual",
            "content": text_to_document("阿宁是右撇子。他没有改口。"),
        },
    )
    assert conflicted.status_code == 200, conflicted.text
    rejected = auth_client.post(
        f"/api/v1/quality-repairs/{candidate['id']}/accept",
        json={"target_revision": candidate["target_revision"]},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "REVISION_CONFLICT"
    assert "没有覆盖" in rejected.json()["error"]["message"]
    assert "他没有改口" in _chapter_body(auth_client, current)
    blocked = auth_client.get(f"/api/v1/quality-issues/{issue['id']}")
    assert blocked.json()["candidates"][0]["status"] == "conflict"
    assert blocked.json()["status"] == "pending"

    refreshed = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert refreshed.status_code == 200, refreshed.text
    issue = refreshed.json()["issues"][0]
    suggested = auth_client.post(f"/api/v1/quality-issues/{issue['id']}/repairs", json={})
    assert suggested.status_code == 200, suggested.text
    candidate = next(item for item in suggested.json()["candidates"] if item["applicable"])
    accepted = auth_client.post(
        f"/api/v1/quality-repairs/{candidate['id']}/accept",
        json={"target_revision": candidate["target_revision"]},
    )
    assert accepted.status_code == 200, accepted.text
    decision = accepted.json()
    assert decision["manuscript_changed"] is True
    assert decision["formal_memory_changed"] is False
    assert decision["issue"]["status"] == "fixed"
    assert decision["chapter"]["revision"] == candidate["target_revision"] + 1
    assert "阿宁是左撇子" in document_to_text(decision["chapter"]["content"])
    assert "他没有改口" in document_to_text(decision["chapter"]["content"])
    versions = auth_client.get(f"/api/v1/chapters/{current}/versions")
    assert versions.status_code == 200, versions.text
    assert versions.json()[0]["change_source"] == "ai_accepted"
    assert versions.json()[0]["change_note"] == "采纳质量修复建议"
    assert auth_client.get(f"/api/v1/novels/{novel}/entities").json() == entities_before.json()
    assert auth_client.get(f"/api/v1/novels/{novel}/events").json() == events_before.json()

    hidden = auth_client.get(f"/api/v1/novels/{novel}/quality-issues")
    assert hidden.json() == []
    visible = auth_client.get(
        f"/api/v1/novels/{novel}/quality-issues",
        params={"status": "fixed"},
    )
    assert [item["id"] for item in visible.json()] == [issue["id"]]

    repeated = auth_client.post(
        f"/api/v1/quality-repairs/{candidate['id']}/accept",
        json={"target_revision": decision["chapter"]["revision"]},
    )
    assert repeated.status_code == 409, repeated.text
    assert _revision(auth_client, current) == decision["chapter"]["revision"]

    _put(auth_client, current, decision["chapter"]["revision"], "阿宁是右撇子。他没有改口。")
    reopened = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["reopened_count"] == 1
    assert reopened.json()["issues"][0]["id"] == issue["id"]
    assert reopened.json()["issues"][0]["status"] == "pending"
    assert reopened.json()["issues"][0]["recheck_count"] == 1


def test_ignored_issue_stays_ignored_and_closed_issues_can_be_listed(
    auth_client: TestClient,
) -> None:
    novel = _novel(auth_client, "忽略")
    source = _save(auth_client, _chapter(auth_client, novel, "前文"), "阿宁是左撇子。")
    current = _save(auth_client, _chapter(auth_client, novel, "后文"), "阿宁是右撇子。")
    _insert_event(
        novel_id=novel,
        chapter_id=source,
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
    )
    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    issue_id = checked.json()["issues"][0]["id"]
    ignored = auth_client.patch(
        f"/api/v1/quality-issues/{issue_id}",
        json={"status": "ignored"},
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["status"] == "ignored"
    default = auth_client.get(f"/api/v1/novels/{novel}/quality-issues")
    assert default.json() == []
    again = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert again.json()["issues"] == []
    listed = auth_client.get(
        f"/api/v1/novels/{novel}/quality-issues",
        params={"include_closed": True},
    )
    assert listed.json()[0]["id"] == issue_id
    assert listed.json()[0]["status"] == "ignored"
    assert listed.json()[0]["chapter_id"] == current


def test_inapplicable_repair_does_not_write(auth_client: TestClient) -> None:
    novel = _novel(auth_client, "不可套用")
    first = _save(auth_client, _chapter(auth_client, novel, "一"), "抽屉里有一把铜钥匙。")
    second = _save(auth_client, _chapter(auth_client, novel, "二"), "计划在这里回收。")
    third = _save(auth_client, _chapter(auth_client, novel, "三"), "人已经出城。")
    created = auth_client.post(
        f"/api/v1/novels/{novel}/foreshadowing",
        json={
            "introduced_chapter_id": first,
            "payoff_chapter_id": second,
            "description": "抽屉里的铜钥匙",
            "status": "planned",
            "evidence_quote": "抽屉里有一把铜钥匙",
        },
    )
    assert created.status_code == 201, created.text
    checked = auth_client.post(f"/api/v1/novels/{novel}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    issue = next(
        item for item in checked.json()["issues"] if item["rule_id"] == "foreshadow.payoff_passed"
    )
    before = _revision(auth_client, third)
    suggested = auth_client.post(f"/api/v1/quality-issues/{issue['id']}/repairs", json={})
    assert suggested.status_code == 200, suggested.text
    candidate = suggested.json()["candidates"][0]
    assert candidate["applicable"] is False
    assert candidate["diff_preview"] == ""
    rejected = auth_client.post(
        f"/api/v1/quality-repairs/{candidate['id']}/accept",
        json={"target_revision": candidate["target_revision"]},
    )
    assert rejected.status_code == 422, rejected.text
    assert _revision(auth_client, third) == before
    assert _chapter_body(auth_client, third) == "人已经出城。"


def test_mock_model_check_does_not_call_network(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("mock quality check tried to call a model")

    monkeypatch.setattr(issue_service, "generate_conflict_text", explode)
    novel = _novel(auth_client, "模拟")
    _save(auth_client, _chapter(auth_client, novel, "空章"), "平安无事。")
    config = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "模拟",
            "provider_type": "mock",
            "base_url": "http://127.0.0.1:9/v1",
            "model_name": "mock",
            "is_enabled": True,
        },
    )
    assert config.status_code == 201, config.text
    checked = auth_client.post(
        f"/api/v1/novels/{novel}/quality-check",
        json={"use_model": True, "model_config_id": config.json()["id"]},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["provider_mode"] == "mock"
    assert checked.json()["manuscript_changed"] is False
    assert "没有访问外部模型" in checked.json()["message"]


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
    response = client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={
            "revision": revision,
            "save_kind": "manual",
            "content": text_to_document(text_value),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _revision(client: TestClient, chapter_id: str) -> int:
    response = client.get(f"/api/v1/chapters/{chapter_id}")
    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
    assert isinstance(revision, int)
    return revision


def _chapter_body(client: TestClient, chapter_id: str) -> str:
    response = client.get(f"/api/v1/chapters/{chapter_id}")
    assert response.status_code == 200, response.text
    return document_to_text(response.json()["content"])


def _snapshot(client: TestClient, novel_id: str, chapter_ids: list[str]) -> dict[str, object]:
    chapters = []
    for chapter_id in chapter_ids:
        response = client.get(f"/api/v1/chapters/{chapter_id}")
        assert response.status_code == 200, response.text
        chapters.append(response.json())
    entities = client.get(f"/api/v1/novels/{novel_id}/entities")
    events = client.get(f"/api/v1/novels/{novel_id}/events")
    assert entities.status_code == 200
    assert events.status_code == 200
    return {"chapters": chapters, "entities": entities.json(), "events": events.json()}


def _insert_event(*, novel_id: str, chapter_id: str, description: str, quote: str) -> None:
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
                    'confirmed', '2026-01-01 00:00:00', NULL
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "novel_id": novel_id,
                "chapter_id": chapter_id,
                "description": description,
                "quote": quote,
            },
        )
    engine.dispose()
