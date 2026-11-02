"""Chapter N must not see facts that only exist in a later chapter."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.ai.prompts import build_conflict_prompt, build_prompt
from app.core.config import get_settings
from app.core.errors import ContextCausalViolation
from app.services.conflicts import ConfirmedFact, _trim_facts
from app.services.context_builder import _assert_causal_cutoff, _Candidate

_NUMERALS = "一二三四五六七八九"
_FUTURE = (
    "FUTURE9_SUMMARY",
    "FUTURE9_STATE",
    "FUTURE9_EVENT",
    "FUTURE9_RELATION",
    "FUTURE9_HOOK",
    "FUTURE9_OUTLINE",
)
_PAST = (
    "PAST1_SUMMARY",
    "PAST1_STATE",
    "PAST1_EVENT",
    "PAST1_RELATION",
    "PAST1_HOOK",
)


def test_prompt_says_unlisted_later_plot_does_not_exist_yet() -> None:
    prompt = build_prompt(
        task_type="continue",
        instruction="接着写",
        chapter_text="阿宁站在门口。",
        selection_text="",
        constraints=None,
    )
    assert "还不存在" in prompt
    assert "尚未发生" in prompt
    conflict = build_conflict_prompt(
        chapter_text="阿宁不是左撇子。",
        facts=[],
        chapter_title="第三章",
    )
    assert "第三章" in conflict
    assert "还不存在" in conflict
    assert "更后面的章节还没发生" in conflict


def test_fact_window_keeps_the_quote_that_overlaps_the_chapter() -> None:
    filler = [
        (
            index,
            ConfirmedFact(
                description=f"旁支{index}是闲笔",
                source_chapter_id="earlier",
                source_quote=f"旁支{index}是闲笔",
            ),
        )
        for index in range(50)
    ]
    relevant = (
        49,
        ConfirmedFact(
            description="阿宁是左撇子",
            source_chapter_id="earlier",
            source_quote="阿宁是左撇子",
        ),
    )
    kept = _trim_facts([*filler, relevant], "阿宁不是左撇子。")
    assert len(kept) == 40
    assert any(item.source_quote == "阿宁是左撇子" for item in kept)


def test_assert_rejects_a_future_fact_and_accepts_a_labeled_plan() -> None:
    future = _Candidate(
        id="event:future",
        kind="event",
        content="第九章才发生",
        source_type="story_event",
        source_id="event-9",
        source_revision=1,
        certainty="confirmed",
        priority=30,
        sequence=0,
        hit_reason="test",
        droppable=True,
        shrinkable=False,
        included=True,
        exclusion_reason=None,
        chapter_order=8,
    )
    with pytest.raises(ContextCausalViolation) as caught:
        _assert_causal_cutoff([future], 2)
    assert caught.value.code == "CONTEXT_CAUSAL_VIOLATION"

    plan = _Candidate(
        id="outline:now",
        kind="chapter_outline",
        content="已确认章节大纲（计划，尚未发生）：写到门口",
        source_type="chapter_outline",
        source_id="outline",
        source_revision=1,
        certainty="confirmed",
        priority=2,
        sequence=1,
        hit_reason="已确认章节大纲",
        droppable=False,
        shrinkable=False,
        included=True,
        exclusion_reason=None,
        plan_not_happened=True,
        chapter_order=8,
    )
    _assert_causal_cutoff([plan], 2)


def test_chapter_three_cannot_see_chapter_nine(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("causal cutoff tried to open a network client")

    monkeypatch.setattr(httpx, "Client", explode)
    novel_id, chapters = _nine_chapters(auth_client)
    third = chapters[2]
    ninth = chapters[8]
    _accept_summary(auth_client, chapters[0])
    _accept_summary(auth_client, ninth)
    ning, gate = _people(auth_client, novel_id)
    _state(auth_client, ning, chapters[0]["id"], "旧伤证据PAST1_STATE")
    _state(auth_client, ning, ninth["id"], "南境证据FUTURE9_STATE")
    _event(
        auth_client,
        novel_id,
        chapters[0]["id"],
        "铜铃旁阿宁是左撇子，旧伤PAST1_EVENT",
        "阿宁是左撇子",
    )
    _event(
        auth_client,
        novel_id,
        ninth["id"],
        "铜铃旁阿宁是独眼，未来FUTURE9_EVENT",
        "阿宁是独眼",
    )
    _relation(auth_client, novel_id, ning, gate, chapters[0]["id"], "旧关系PAST1_RELATION")
    _relation(auth_client, novel_id, ning, gate, ninth["id"], "未来关系FUTURE9_RELATION")
    _hook(auth_client, novel_id, chapters[0]["id"], "阿宁把铜铃埋下，旧伏笔PAST1_HOOK")
    _hook(auth_client, novel_id, ninth["id"], "阿宁把铜铃揭开，未来伏笔FUTURE9_HOOK")
    _confirm_outline(auth_client, third["id"], "本章要写到门口")
    _confirm_outline(auth_client, ninth["id"], "FUTURE9_OUTLINE才揭晓")

    earlier = _compile(auth_client, novel_id, third)
    blob = json.dumps(earlier, ensure_ascii=False)
    for token in _PAST:
        assert token in blob
    for token in _FUTURE:
        assert token not in blob
    assert "第九章" not in blob
    assert "事实截至：第三章。" in blob
    assert "还不存在" in blob
    assert "尚未发生" in blob
    assert "截至本章的状态" in blob
    assert "南境证据FUTURE9_STATE" not in blob

    later = _compile(auth_client, novel_id, ninth)
    later_blob = json.dumps(later, ensure_ascii=False)
    assert "事实截至：第九章。" in later_blob
    assert "南境证据FUTURE9_STATE" in later_blob
    assert "PAST1_SUMMARY" in later_blob
    assert "FUTURE9_OUTLINE" in later_blob
    assert "尚未发生" in later_blob

    checked = auth_client.post(
        f"/api/v1/chapters/{third['id']}/conflict-check",
        json={"use_mock": True},
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    quotes = [item["source_quote"] for item in body["conflicts"]]
    titles = [item["source_chapter_title"] for item in body["conflicts"]]
    assert "阿宁是左撇子" in quotes
    assert "阿宁是独眼" not in quotes
    assert all("FUTURE9" not in json.dumps(item, ensure_ascii=False) for item in body["conflicts"])
    assert "第九章" not in titles
    assert "第一章" in titles

    created = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel_id,
            "chapter_id": third["id"],
            "task_type": "continue",
            "instruction": "铜铃",
            "target_revision": third["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
        },
    )
    assert created.status_code == 201, created.text
    prompt = str(_snapshot()["prompt"])
    assert "事实截至：第三章。" in prompt
    assert "还不存在" in prompt
    for token in _FUTURE:
        assert token not in prompt


def test_compile_assert_returns_causal_violation(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.context_builder as compiler

    real = compiler._collect

    def leak(*args: object, **kwargs: object) -> tuple[list[_Candidate], int | None]:
        candidates, order = real(*args, **kwargs)
        candidates.append(
            _Candidate(
                id="event:planted-future",
                kind="event",
                content="泄漏FUTURE9_ASSERT",
                source_type="story_event",
                source_id="planted",
                source_revision=1,
                certainty="confirmed",
                priority=1,
                sequence=0,
                hit_reason="test",
                droppable=True,
                shrinkable=False,
                included=True,
                exclusion_reason=None,
                chapter_order=(order or 0) + 4,
            )
        )
        return candidates, order

    monkeypatch.setattr(compiler, "_collect", leak)
    novel = auth_client.post("/api/v1/novels", json={"title": "断言"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第三章"},
    ).json()
    response = auth_client.post(
        "/api/v1/ai/tasks/context/compile",
        json={
            "novel_id": novel["id"],
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "写",
            "target_revision": chapter["revision"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTEXT_CAUSAL_VIOLATION"
    assert "泄漏FUTURE9_ASSERT" not in response.text


def _nine_chapters(client: TestClient) -> tuple[str, list[dict[str, object]]]:
    novel = client.post("/api/v1/novels", json={"title": "因果"}).json()
    chapters: list[dict[str, object]] = []
    for index in range(9):
        title = f"第{_NUMERALS[index]}章"
        created = client.post(
            f"/api/v1/novels/{novel['id']}/chapters",
            json={"title": title},
        )
        assert created.status_code == 201, created.text
        saved = client.put(
            f"/api/v1/chapters/{created.json()['id']}",
            json={
                "revision": created.json()["revision"],
                "save_kind": "manual",
                "content": _document(_chapter_text(index)),
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert isinstance(body, dict)
        chapters.append(body)
    return str(novel["id"]), chapters


def _chapter_text(index: int) -> str:
    if index == 0:
        return "第一章旧摘要PAST1_SUMMARY留在这里。"
    if index == 2:
        return "阿宁不是左撇子。阿宁不是独眼。阿宁站在门口。"
    if index == 3:
        return "第四章只是衔接。"
    if index == 8:
        return "第九章未来摘要FUTURE9_SUMMARY留在这里。阿宁还在。"
    return "这一章先空着。"


def _document(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _accept_summary(client: TestClient, chapter: dict[str, object]) -> None:
    analyzed = client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": True},
    )
    assert analyzed.status_code == 200, analyzed.text
    summary = next(
        item for item in analyzed.json()["proposals"] if item["proposal_type"] == "chapter_summary"
    )
    accepted = client.post(f"/api/v1/memory-proposals/{summary['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text


def _people(client: TestClient, novel_id: str) -> tuple[str, str]:
    ning = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": "character", "name": "阿宁", "profile": {"summary": "人物"}},
    )
    gate = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": "location", "name": "城门", "profile": {"summary": "地点"}},
    )
    assert ning.status_code == 201, ning.text
    assert gate.status_code == 201, gate.text
    return str(ning.json()["id"]), str(gate.json()["id"])


def _state(client: TestClient, entity_id: str, chapter_id: object, evidence: str) -> None:
    created = client.post(
        f"/api/v1/entities/{entity_id}/states",
        json={
            "chapter_id": chapter_id,
            "state_data": {"note": evidence},
            "evidence_quote": evidence,
        },
    )
    assert created.status_code == 201, created.text


def _event(
    client: TestClient,
    novel_id: str,
    chapter_id: object,
    description: str,
    quote: str,
) -> None:
    created = client.post(
        f"/api/v1/novels/{novel_id}/events",
        json={
            "description": description,
            "evidence_quote": quote,
            "chapter_id": chapter_id,
            "certainty": "confirmed",
        },
    )
    assert created.status_code == 201, created.text


def _relation(
    client: TestClient,
    novel_id: str,
    left: str,
    right: str,
    chapter_id: object,
    evidence: str,
) -> None:
    created = client.post(
        f"/api/v1/novels/{novel_id}/relations",
        json={
            "from_entity_id": left,
            "to_entity_id": right,
            "relation_type": "守着",
            "source_chapter_id": chapter_id,
            "evidence_quote": evidence,
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text


def _hook(client: TestClient, novel_id: str, chapter_id: object, description: str) -> None:
    created = client.post(
        f"/api/v1/novels/{novel_id}/foreshadowing",
        json={
            "introduced_chapter_id": chapter_id,
            "description": description,
            "status": "open",
        },
    )
    assert created.status_code == 201, created.text


def _confirm_outline(client: TestClient, chapter_id: object, goal: str) -> None:
    saved = client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={"goal": goal},
    )
    assert saved.status_code == 200, saved.text
    confirmed = client.post(
        f"/api/v1/chapters/{chapter_id}/outline/confirm",
        json={"expected_revision": saved.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text


def _compile(
    client: TestClient,
    novel_id: str,
    chapter: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        "/api/v1/ai/tasks/context/compile",
        json={
            "novel_id": novel_id,
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "铜铃",
            "target_revision": chapter["revision"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _snapshot() -> dict[str, object]:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT input_snapshot FROM ai_tasks ORDER BY created_at DESC")
        ).scalar_one()
    engine.dispose()
    snapshot = json.loads(stored) if isinstance(stored, str) else stored
    assert isinstance(snapshot, dict)
    return snapshot
