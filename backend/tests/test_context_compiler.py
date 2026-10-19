"""Context compiler selection, budget, isolation, and task snapshots."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.services.context_builder import COMPILER_VERSION

PARAGRAPH = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "林晚说道：“继续走。”"}]}
    ],
}


def test_compile_requires_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ai/tasks/context/compile",
        json={"novel_id": "missing", "task_type": "continue"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_empty_novel_compiles_without_pretending_to_fail(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "空白"}).json()
    compiled = _compile(auth_client, novel["id"], None, instruction="")
    kinds = {item["kind"] for item in compiled["items"] if item["included"]}
    assert "system" in kinds
    assert "instruction" in kinds
    assert compiled["legacy"] is False
    assert compiled["compiler_version"] == COMPILER_VERSION
    assert compiled["warnings"] == [] or isinstance(compiled["warnings"], list)


def test_same_input_is_stable_and_draft_plan_is_not_a_fact(auth_client: TestClient) -> None:
    novel_id, chapter = _chapter(auth_client, "稳定", "硬规则甲")
    auth_client.put(
        f"/api/v1/novels/{novel_id}/story-plan",
        json={"body": "草稿全书大纲甲"},
    )
    outline = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}/outline",
        json={"goal": "草稿章节目标甲", "forbidden_reveals": "不能写出城里已经空了"},
    )
    assert outline.status_code == 200, outline.text
    auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"goal": "草稿场景甲", "must_not_reveal": "城里没人"},
    )
    first = _compile(auth_client, novel_id, chapter, instruction="顺着写")
    second = _compile(auth_client, novel_id, chapter, instruction="顺着写")
    assert [(item["id"], item["included"]) for item in first["items"]] == [
        (item["id"], item["included"]) for item in second["items"]
    ]
    assert first["context_hash"] == second["context_hash"]
    draft_outline = _item_containing(first, "草稿章节目标甲")
    draft_scene = _item_containing(first, "草稿场景甲")
    draft_plan = _item_containing(first, "草稿全书大纲甲")
    assert draft_outline["included"] is False
    assert draft_scene["included"] is False
    assert draft_plan["included"] is False
    assert "草稿" in draft_outline["exclusion_reason"]
    assert "不是事实" in draft_outline["content"]

    confirmed = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/outline/confirm",
        json={"expected_revision": outline.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    scene = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"goal": "已确认场景甲", "status": "confirmed", "must_not_reveal": "不能提前说出钥匙"},
    )
    assert scene.status_code == 201, scene.text
    fact = _compile(
        auth_client,
        novel_id,
        chapter,
        instruction="请写出不能写出城里已经空了",
    )
    included_outline = _item_containing(fact, "草稿章节目标甲")
    included_scene = _item_containing(fact, "已确认场景甲")
    assert included_outline["included"] is True
    assert included_outline["certainty"] == "confirmed"
    assert included_outline["source_type"] == "chapter_outline"
    assert included_outline["hit_reason"] == "已确认章节大纲"
    assert included_scene["included"] is True
    assert any("禁止揭露" in warning for warning in fact["warnings"])
    stored = auth_client.get(f"/api/v1/chapters/{chapter['id']}/outline").json()["outline"]
    assert stored["status"] == "confirmed"
    assert stored["goal"] == "草稿章节目标甲"


def test_hard_rule_is_kept_whole_when_budget_is_too_small(auth_client: TestClient) -> None:
    guide = "规" * 500
    novel_id, chapter = _chapter(auth_client, "预算", guide)
    compiled = _compile(auth_client, novel_id, chapter, instruction="写", budget=200)
    rule = next(item for item in compiled["items"] if item["kind"] == "hard_rule")
    assert rule["included"] is True
    assert guide in rule["content"]
    assert rule["exclusion_reason"] is None
    assert len(rule["content"]) > 80
    assert any("没有静默截断" in warning for warning in compiled["warnings"])
    distant = _item_or_none(compiled, "远距离摘要标记")
    assert distant is None or distant["included"] is False


def test_cross_novel_material_never_enters_context(auth_client: TestClient) -> None:
    first_id, chapter = _chapter(auth_client, "作品甲", "硬规则甲")
    second = auth_client.post(
        "/api/v1/novels",
        json={"title": "作品乙", "style_guide": "乙书硬规则"},
    ).json()
    second_chapter = auth_client.post(
        f"/api/v1/novels/{second['id']}/chapters",
        json={"title": "乙章"},
    ).json()
    auth_client.put(
        f"/api/v1/novels/{second['id']}/story-plan",
        json={"body": "乙书大纲机密"},
    )
    other_outline = auth_client.put(
        f"/api/v1/chapters/{second_chapter['id']}/outline",
        json={"goal": "乙书章节大纲机密"},
    )
    assert other_outline.status_code == 200, other_outline.text
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
        f"/api/v1/novels/{first_id}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "aliases": ["晚晚"],
            "profile": {"summary": "左臂旧伤"},
            "status": "active",
        },
    )
    auth_client.post(
        f"/api/v1/novels/{second['id']}/foreshadowing",
        json={
            "introduced_chapter_id": second_chapter["id"],
            "description": "乙书伏笔暗号",
            "status": "open",
        },
    )
    own_hook = auth_client.post(
        f"/api/v1/novels/{first_id}/foreshadowing",
        json={
            "introduced_chapter_id": chapter["id"],
            "description": "铜铃还没有响",
            "status": "open",
        },
    )
    assert own_hook.status_code == 201, own_hook.text
    renamed = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "save_kind": "manual",
            "content": _document("晚晚继续往前走。"),
        },
    )
    assert renamed.status_code == 200, renamed.text
    compiled = _compile(auth_client, first_id, renamed.json(), instruction="晚晚继续走")
    blob = json.dumps(compiled, ensure_ascii=False)
    assert "左臂旧伤" in blob
    assert "铜铃还没有响" in blob
    assert "硬规则甲" in blob
    for secret in (
        "乙书不应出现",
        "乙书大纲机密",
        "乙书章节大纲机密",
        "乙书伏笔暗号",
        "乙书硬规则",
    ):
        assert secret not in blob
    alias = _item_containing(compiled, "左臂旧伤")
    assert alias["included"] is True
    assert "别名" in alias["hit_reason"]
    pinned = _compile(
        auth_client,
        first_id,
        renamed.json(),
        instruction="顺着写",
        pinned_include=[f"outline:{other_outline.json()['id']}"],
    )
    pinned_blob = json.dumps(pinned, ensure_ascii=False)
    assert "乙书章节大纲机密" not in pinned_blob
    assert any("没有读取其他作品" in warning for warning in pinned["warnings"])


def test_stale_summary_and_revision_mismatch_are_warnings(auth_client: TestClient) -> None:
    novel_id, chapter = _chapter(auth_client, "过期来源", "硬规则甲")
    previous = auth_client.post(
        f"/api/v1/novels/{novel_id}/chapters",
        json={"title": "序章"},
    ).json()
    # Reading order follows sort_order. The first created chapter is current if we compile it.
    analyzed = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": True},
    )
    assert analyzed.status_code == 200, analyzed.text
    summary = next(
        item for item in analyzed.json()["proposals"] if item["proposal_type"] == "chapter_summary"
    )
    accepted = auth_client.post(f"/api/v1/memory-proposals/{summary['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    _insert_event(
        novel_id=novel_id,
        chapter_id=str(chapter["id"]),
        source_revision=1,
        description="钟声在夜里响过",
        evidence="钟声",
    )
    saved = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "save_kind": "manual",
            "content": _document("林晚说道：“又走了一步。”"),
        },
    )
    assert saved.status_code == 200, saved.text
    compiled = _compile(
        auth_client,
        novel_id,
        saved.json(),
        instruction="钟声",
    )
    stale_items = [
        item
        for item in compiled["items"]
        if item["kind"] == "summary" and item["included"] is False
    ]
    assert stale_items
    assert any("过期" in (item["exclusion_reason"] or "") for item in stale_items)
    assert any("过期" in warning or "落后" in warning for warning in compiled["warnings"])
    event = _item_containing(compiled, "钟声在夜里响过")
    assert event["included"] is True
    assert any("落后" in warning for warning in event["warnings"])
    assert previous["id"] != chapter["id"]


def test_pins_change_only_this_compile(auth_client: TestClient) -> None:
    novel_id, chapter = _chapter(auth_client, "固定", "硬规则甲" * 30)
    outline = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}/outline",
        json={"goal": "只在固定时出现的草稿"},
    )
    assert outline.status_code == 200, outline.text
    outline_id = f"outline:{outline.json()['id']}"
    excluded = _compile(
        auth_client,
        novel_id,
        chapter,
        instruction="写",
        budget=200,
        pinned_exclude=["hard-rule", "system"],
    )
    rule = next(item for item in excluded["items"] if item["id"] == "hard-rule")
    system = next(item for item in excluded["items"] if item["id"] == "system")
    assert rule["included"] is False
    assert rule["exclusion_reason"] == "用户本次排除"
    assert system["included"] is True
    assert any("不能从本次上下文排除" in warning for warning in excluded["warnings"])
    assert any("排除了作品硬规则" in warning for warning in excluded["warnings"])
    forced = _compile(
        auth_client,
        novel_id,
        chapter,
        instruction="写",
        pinned_include=[outline_id],
    )
    draft = next(item for item in forced["items"] if item["id"] == outline_id)
    assert draft["included"] is True
    assert any("不是已确认事实" in warning for warning in draft["warnings"])
    stored = auth_client.get(f"/api/v1/chapters/{chapter['id']}/outline").json()["outline"]
    assert stored["status"] == "draft"
    assert stored["revision"] == outline.json()["revision"]


def test_mock_task_stores_context_and_hides_secrets(auth_client: TestClient) -> None:
    secret = "sk-supersecretvalue"
    novel_id, chapter = _chapter(auth_client, "快照", "硬规则甲")
    created_model = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "外部服务",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "demo-model",
            "api_key": secret,
        },
    )
    assert created_model.status_code == 201, created_model.text
    task = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel_id,
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": f"不要保存 api_key={secret}",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
            "pinned_exclude": ["hard-rule"],
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["status"] == "queued"
    context = auth_client.get(f"/api/v1/ai/tasks/{task.json()['id']}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["compiler_version"] == COMPILER_VERSION
    assert body["legacy"] is False
    assert any(item["id"] == "hard-rule" and item["included"] is False for item in body["items"])
    stored = _snapshot()
    raw = json.dumps(stored, ensure_ascii=False)
    secret_ref = _secret_ref()
    assert secret not in raw
    assert secret_ref not in raw
    assert "secret_ref" not in stored
    assert "api_key" not in stored
    prompt = stored["prompt"]
    assert isinstance(prompt, str)
    assert "硬规则甲" not in prompt
    assert "[REDACTED]" in prompt or secret not in prompt
    chapter_after = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert chapter_after.json()["revision"] == chapter["revision"]


def test_legacy_task_snapshot_does_not_invent_items(auth_client: TestClient) -> None:
    novel_id, chapter = _chapter(auth_client, "旧任务", None)
    task = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel_id,
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "旧",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
        },
    )
    assert task.status_code == 201, task.text
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ai_tasks SET input_snapshot = :snapshot WHERE id = :task_id"),
            {
                "task_id": task.json()["id"],
                "snapshot": json.dumps(
                    {
                        "prompt": "只有整段提示",
                        "provider_mode": "mock",
                        "model_name": "mock",
                        "target_revision": chapter["revision"],
                    },
                    ensure_ascii=False,
                ),
            },
        )
    engine.dispose()
    context = auth_client.get(f"/api/v1/ai/tasks/{task.json()['id']}/context")
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["legacy"] is True
    assert body["items"] == []
    assert any("整段提示" in warning for warning in body["warnings"])


def test_compile_failure_does_not_create_a_task(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id, chapter = _chapter(auth_client, "失败", "硬规则甲")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("api_key=sk-supersecretvalue")

    monkeypatch.setattr("app.services.ai_tasks.compile_context", explode)
    before = _task_count()
    response = auth_client.post(
        "/api/v1/ai/tasks",
        json={
            "novel_id": novel_id,
            "chapter_id": chapter["id"],
            "task_type": "continue",
            "instruction": "写",
            "target_revision": chapter["revision"],
            "use_mock": True,
            "mock_tokens": ["甲"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTEXT_COMPILE_FAILED"
    assert "sk-" not in response.text
    assert "traceback" not in response.text.lower()
    assert _task_count() == before


def test_selection_rewrite_skips_distant_summary(auth_client: TestClient) -> None:
    novel_id, earlier = _chapter(auth_client, "选区", None)
    saved_earlier = auth_client.put(
        f"/api/v1/chapters/{earlier['id']}",
        json={
            "revision": earlier["revision"],
            "save_kind": "manual",
            "content": _document("林晚说道：“序章里的旧伤。”"),
        },
    )
    assert saved_earlier.status_code == 200, saved_earlier.text
    analyzed = auth_client.post(
        f"/api/v1/chapters/{earlier['id']}/analyze",
        json={"revision": saved_earlier.json()["revision"], "use_mock": True},
    )
    summary = next(
        item for item in analyzed.json()["proposals"] if item["proposal_type"] == "chapter_summary"
    )
    assert (
        auth_client.post(f"/api/v1/memory-proposals/{summary['id']}/accept", json={}).status_code
        == 200
    )
    current = auth_client.post(
        f"/api/v1/novels/{novel_id}/chapters",
        json={"title": "正文"},
    ).json()
    saved = auth_client.put(
        f"/api/v1/chapters/{current['id']}",
        json={
            "revision": current["revision"],
            "save_kind": "manual",
            "content": _document("门开着。"),
        },
    ).json()
    compiled = _compile(
        auth_client,
        novel_id,
        saved,
        instruction="改得短一点",
        task_type="rewrite",
        selection_text="门开着。",
    )
    summaries = [item for item in compiled["items"] if item["kind"] == "summary"]
    assert summaries
    assert all(item["included"] is False for item in summaries)
    assert any("选区改写" in (item["exclusion_reason"] or "") for item in summaries)
    blob = json.dumps(compiled, ensure_ascii=False)
    assert "序章里的旧伤" not in blob or all(item["included"] is False for item in summaries)


def _compile(
    client: TestClient,
    novel_id: str,
    chapter: dict[str, object] | None,
    *,
    instruction: str,
    budget: int | None = None,
    pinned_include: list[str] | None = None,
    pinned_exclude: list[str] | None = None,
    task_type: str = "continue",
    selection_text: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "novel_id": novel_id,
        "task_type": task_type,
        "instruction": instruction,
    }
    if chapter is not None:
        payload["chapter_id"] = chapter["id"]
        payload["target_revision"] = chapter["revision"]
    if budget is not None:
        payload["context_budget"] = budget
    if pinned_include is not None:
        payload["pinned_include"] = pinned_include
    if pinned_exclude is not None:
        payload["pinned_exclude"] = pinned_exclude
    if selection_text is not None:
        payload["selection_text"] = selection_text
    response = client.post("/api/v1/ai/tasks/context/compile", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _chapter(
    client: TestClient,
    title: str,
    style_guide: str | None,
) -> tuple[str, dict[str, object]]:
    payload: dict[str, object] = {"title": title}
    if style_guide is not None:
        payload["style_guide"] = style_guide
    novel = client.post("/api/v1/novels", json=payload)
    assert novel.status_code == 201, novel.text
    created = client.post(
        f"/api/v1/novels/{novel.json()['id']}/chapters",
        json={"title": "正文"},
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
    body = saved.json()
    assert isinstance(body, dict)
    return str(novel.json()["id"]), body


def _item_containing(compiled: dict[str, object], text: str) -> dict[str, object]:
    items = compiled["items"]
    assert isinstance(items, list)
    found = next(
        item for item in items if isinstance(item, dict) and text in str(item.get("content"))
    )
    assert isinstance(found, dict)
    return found


def _item_or_none(compiled: dict[str, object], text: str) -> dict[str, object] | None:
    items = compiled["items"]
    assert isinstance(items, list)
    for item in items:
        if isinstance(item, dict) and text in str(item.get("content")):
            return item
    return None


def _insert_event(
    *,
    novel_id: str,
    chapter_id: str,
    source_revision: int,
    description: str,
    evidence: str,
) -> None:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO story_events (
                    id, novel_id, chapter_id, source_revision, description,
                    participants, evidence_quote, certainty, created_at
                ) VALUES (
                    :id, :novel_id, :chapter_id, :source_revision, :description,
                    :participants, :evidence, 'confirmed', :created_at
                )
                """
            ),
            {
                "id": "event-stale-source",
                "novel_id": novel_id,
                "chapter_id": chapter_id,
                "source_revision": source_revision,
                "description": description,
                "participants": "[]",
                "evidence": evidence,
                "created_at": datetime.now(UTC),
            },
        )
    engine.dispose()


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


def _secret_ref() -> str:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT secret_ref FROM model_configs")).scalar_one()
    engine.dispose()
    assert isinstance(stored, str)
    assert stored != ""
    return stored


def _task_count() -> int:
    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM ai_tasks")).scalar_one()
    engine.dispose()
    assert isinstance(count, int)
    return count


def _document(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }
