"""Manuscript and material sync: candidates stay separate until confirmed."""

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.registry import set_test_transport
from app.services.quality_rules import (
    ArcMaterial,
    ChapterMaterial,
    EntityMaterial,
    EventMaterial,
    ForeshadowMaterial,
    QualityFinding,
    QualityMaterials,
    RelationMaterial,
    StateMaterial,
    run_rules,
)


@pytest.fixture(autouse=True)
def _clear_transport() -> Iterator[None]:
    set_test_transport(None)
    yield
    set_test_transport(None)


def test_light_check_does_not_call_the_model_or_write_formal_memory(
    auth_client: TestClient,
) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        del request
        raise AssertionError("light check called the model")

    set_test_transport(httpx.MockTransport(explode))
    novel, chapter = _chapter(
        auth_client,
        "轻量",
        "林晚是城门的守卫。抽屉里的钥匙是伏笔。设定：夜里不离城门。他已经死了。",
    )
    analyzed = _analyze(auth_client, chapter, scope="light")
    assert analyzed["provider_mode"] == "rule"
    assert analyzed["model_config_id"] is None
    assert analyzed["formal_memory_changed"] is False
    assert analyzed["manuscript_changed"] is False
    kinds = {item["proposal_type"] for item in analyzed["proposals"]}
    assert kinds == {
        "entity_relation",
        "foreshadowing",
        "setting_supplement",
        "potential_conflict",
    }
    for item in analyzed["proposals"]:
        assert item["source_chapter_id"] == chapter["id"]
        assert item["evidence_quote"]
        assert item["evidence_quote"] in _text(chapter)
        assert item["status"] == "pending"

    again = _analyze(auth_client, chapter, scope="light")
    assert again["proposal_count"] == 0
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json() == []
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/relations").json() == []
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/foreshadowing").json() == []


def test_review_actions_write_formal_material_only_after_confirm(auth_client: TestClient) -> None:
    novel, chapter = _chapter(
        auth_client,
        "审核",
        "林晚是城门的守卫。抽屉里的钥匙是伏笔。设定：夜里不离城门。他已经死了。",
    )
    lin = _entity(auth_client, str(novel["id"]), "character", "林晚")
    _entity(auth_client, str(novel["id"]), "location", "城门")
    analyzed = _analyze(auth_client, chapter, scope="light")
    by_type = {item["proposal_type"]: item for item in analyzed["proposals"]}

    deferred = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['entity_relation']['id']}/defer",
        json={},
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["status"] == "deferred"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/relations").json() == []

    accepted_relation = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['entity_relation']['id']}/accept",
        json={},
    )
    assert accepted_relation.status_code == 200, accepted_relation.text
    relations = auth_client.get(f"/api/v1/novels/{novel['id']}/relations").json()
    assert len(relations) == 1
    assert relations[0]["relation_type"] == "守卫"
    assert relations[0]["evidence_quote"]

    reverted = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['entity_relation']['id']}/revert",
        json={},
    )
    assert reverted.status_code == 200, reverted.text
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/relations").json() == []

    foreshadow = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['foreshadowing']['id']}/accept",
        json={
            "edits": {
                "event_time_text": "第1天",
                "character_discovered_text": "第3天",
                "reader_revealed_text": "第三章",
            }
        },
    )
    assert foreshadow.status_code == 200, foreshadow.text
    hooks = auth_client.get(f"/api/v1/novels/{novel['id']}/foreshadowing").json()
    assert len(hooks) == 1
    assert hooks[0]["event_time_text"] == "第1天"
    assert hooks[0]["character_discovered_text"] == "第3天"
    assert hooks[0]["reader_revealed_text"] == "第三章"
    assert hooks[0]["introduced_chapter_id"] == chapter["id"]
    assert hooks[0]["status"] == "open"

    supplement = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['setting_supplement']['id']}/accept",
        json={"edits": {"target_name": "林晚"}},
    )
    assert supplement.status_code == 200, supplement.text
    stored = auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json()
    matched = next(item for item in stored if item["id"] == lin["id"])
    supplements = matched["profile"]["supplements"]
    assert supplements[0]["text"] == "夜里不离城门"
    changed = auth_client.patch(
        f"/api/v1/entities/{lin['id']}",
        json={"profile": {"summary": "后来改过的档案"}},
    )
    assert changed.status_code == 200, changed.text
    blocked = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['setting_supplement']['id']}/revert",
        json={},
    )
    assert blocked.status_code == 409, blocked.text
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json()
    kept = next(item for item in listed if item["id"] == lin["id"])
    assert kept["profile"]["summary"] == "后来改过的档案"
    assert "supplements" not in kept["profile"]

    conflict = auth_client.post(
        f"/api/v1/memory-proposals/{by_type['potential_conflict']['id']}/intentional",
        json={},
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["status"] == "intentional"
    issues = auth_client.get(
        f"/api/v1/novels/{novel['id']}/quality-issues",
        params={"status": "intentional"},
    )
    assert issues.status_code == 200, issues.text
    assert len(issues.json()) == 1
    assert issues.json()[0]["finding_class"] == "suspected"
    stored = auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json()
    names = {item["name"] for item in stored}
    assert names == {"林晚", "城门"}
    current = auth_client.get(f"/api/v1/chapters/{chapter['id']}")
    assert current.json()["revision"] == chapter["revision"]
    assert current.json()["content"] == chapter["content"]


def test_full_analysis_uses_requested_or_default_model(auth_client: TestClient) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body.get("model")
        assert isinstance(model, str)
        seen.append(model)
        if body.get("messages", [{}])[-1].get("content") == "ping":
            content = "pong"
        else:
            content = json.dumps(
                {
                    "proposals": [
                        {
                            "proposal_type": "entity_create",
                            "certainty": "confirmed",
                            "evidence_quote": "林晚说道：夜里城门已经关了。",
                            "payload": {
                                "entity_type": "character",
                                "name": "林晚",
                                "aliases": [],
                                "profile": {"summary": "守门"},
                                "status": "active",
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
    chosen = auth_client.put(f"/api/v1/settings/models/{first['id']}/default")
    assert chosen.status_code == 200, chosen.text

    _novel, chapter = _chapter(auth_client, "模型", "林晚说道：夜里城门已经关了。")
    seen.clear()
    defaulted = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": False, "scope": "full"},
    )
    assert defaulted.status_code == 200, defaulted.text
    assert defaulted.json()["model_config_id"] == first["id"]
    assert defaulted.json()["provider_mode"] == "openai_compatible"
    assert seen == ["model-a"]
    assert defaulted.json()["formal_memory_changed"] is False

    picked = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={
            "revision": chapter["revision"],
            "use_mock": False,
            "scope": "full",
            "model_config_id": second["id"],
        },
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["model_config_id"] == second["id"]
    assert seen[-1] == "model-b"


def test_material_impact_lists_related_rows_without_writing(auth_client: TestClient) -> None:
    novel, chapter = _chapter(auth_client, "影响", "林晚仍在城门。")
    lin = _entity(auth_client, str(novel["id"]), "character", "林晚")
    gate = _entity(auth_client, str(novel["id"]), "location", "城门")
    relation = auth_client.post(
        f"/api/v1/novels/{novel['id']}/relations",
        json={
            "from_entity_id": lin["id"],
            "to_entity_id": gate["id"],
            "relation_type": "驻守",
            "source_chapter_id": chapter["id"],
            "evidence_quote": "林晚仍在城门。",
        },
    )
    assert relation.status_code == 201, relation.text
    state = auth_client.post(
        f"/api/v1/entities/{lin['id']}/states",
        json={"chapter_id": chapter["id"], "state_data": {"summary": "守着"}},
    )
    assert state.status_code == 201, state.text
    before_rows = auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json()
    before_entity = next(item for item in before_rows if item["id"] == lin["id"])
    before_chapter = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()

    impact = auth_client.get(
        f"/api/v1/novels/{novel['id']}/material-impact",
        params={"kind": "entity", "target_id": lin["id"]},
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert body["manuscript_changed"] is False
    assert body["formal_memory_changed"] is False
    affected = {item["id"] for item in body["affected"]}
    assert relation.json()["id"] in affected
    assert state.json()["id"] in affected

    after_rows = auth_client.get(f"/api/v1/novels/{novel['id']}/entities").json()
    after_entity = next(item for item in after_rows if item["id"] == lin["id"])
    after_chapter = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()
    assert after_entity["updated_at"] == before_entity["updated_at"]
    assert after_entity["name"] == before_entity["name"]
    assert after_chapter["revision"] == before_chapter["revision"]
    assert after_chapter["content"] == before_chapter["content"]


def test_quality_issue_keeps_finding_class_and_review_status(auth_client: TestClient) -> None:
    novel, _chapter_row = _chapter(auth_client, "规则", "他违反了不能夜行。")
    created = _entity(auth_client, str(novel["id"]), "rule", "不能夜行")
    assert created["entity_type"] == "rule"
    checked = auth_client.post(f"/api/v1/novels/{novel['id']}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    assert checked.json()["manuscript_changed"] is False
    issue = next(
        item for item in checked.json()["issues"] if item["rule_id"] == "world.rule_negated"
    )
    assert issue["finding_class"] == "deterministic"
    deferred = auth_client.patch(
        f"/api/v1/quality-issues/{issue['id']}",
        json={"status": "deferred"},
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["status"] == "deferred"
    intentional = auth_client.patch(
        f"/api/v1/quality-issues/{issue['id']}",
        json={"status": "intentional"},
    )
    assert intentional.status_code == 200, intentional.text
    assert intentional.json()["status"] == "intentional"
    assert intentional.json()["finding_class"] == "deterministic"


def test_consistency_rules_keep_three_finding_classes() -> None:
    birth = _rules(
        entities=(EntityMaterial("e1", "阿宁", (), birth_time_text="第10天"),),
        events=(EventMaterial("ev1", "c1", "出生前现身", "第1天就出现了", "第1天", ("阿宁",), 1),),
    )
    assert _class(birth, "time.event_before_birth") == "deterministic"

    death = _rules(
        entities=(EntityMaterial("e1", "阿宁", (), death_time_text="第2天"),),
        events=(EventMaterial("ev1", "c1", "死后现身", "第5天又来了", "第5天", ("阿宁",), 1),),
    )
    assert _class(death, "time.event_after_death") == "deterministic"

    unclear = _rules(
        entities=(EntityMaterial("e1", "阿宁", (), birth_time_text="春天"),),
        events=(EventMaterial("ev1", "c1", "那年", "那年春来了", "那年春", ("阿宁",), 1),),
    )
    assert _class(unclear, "time.life_undetermined") == "suspected"

    identity = _rules(
        states=(
            StateMaterial(
                "s1",
                "e1",
                "阿宁",
                "c1",
                (("身份", "捕快"),),
                "阿宁是捕快。",
                "第1天",
                "第5天",
                1,
            ),
            StateMaterial(
                "s2",
                "e1",
                "阿宁",
                "c2",
                (("身份", "游侠"),),
                "阿宁是游侠。",
                "第4天",
                "第6天",
                1,
            ),
        ),
        chapters=_chapters(2),
    )
    assert _class(identity, "character.identity_conflict") == "deterministic"
    assert "time.validity_overlap" not in {item.rule_id for item in identity}

    after_death = _rules(
        states=(
            StateMaterial(
                "s1", "e1", "阿宁", "c1", (("伤势", "死亡"),), "阿宁死了。", "第1天", None, 1
            ),
            StateMaterial(
                "s2", "e1", "阿宁", "c2", (("位置", "京城"),), "人在京城。", "第3天", None, 1
            ),
        ),
        chapters=_chapters(2),
    )
    assert _class(after_death, "character.state_after_death") == "deterministic"

    revived = _rules(
        states=(
            StateMaterial(
                "s1", "e1", "阿宁", "c1", (("伤势", "死亡"),), "阿宁死了。", "第1天", None, 1
            ),
            StateMaterial(
                "s2",
                "e1",
                "阿宁",
                "c2",
                (("位置", "京城"),),
                "阿宁复活后回到京城。",
                "第3天",
                None,
                1,
            ),
        ),
        chapters=_chapters(2),
    )
    assert "character.state_after_death" not in {item.rule_id for item in revived}

    negated = _rules(
        entities=(EntityMaterial("rule-1", "不能夜行", (), entity_type="rule"),),
        chapters=(ChapterMaterial("c1", "夜", 0, 1, "他违反了不能夜行。"),),
    )
    assert _class(negated, "world.rule_negated") == "deterministic"

    risk = _rules(
        entities=(EntityMaterial("rule-1", "不能夜行", (), entity_type="rule"),),
        chapters=(ChapterMaterial("c1", "夜", 0, 1, "不能夜行也许有例外。"),),
    )
    assert _class(risk, "world.rule_risk") == "creative_risk"

    relations = _rules(
        relations=(
            RelationMaterial("r1", "林晚", "城门", "驻守", "林晚驻守城门。", "c1", 1),
            RelationMaterial("r2", "林晚", "城门", "离开", "林晚离开城门。", "c1", 1),
        ),
    )
    assert _class(relations, "relation.type_conflict") == "deterministic"

    planted = ChapterMaterial("c2", "后文", 2, 1, "钥匙还在。")
    earlier = ChapterMaterial("c0", "序章", 0, 1, "还没有钥匙。")
    payoff = _rules(
        chapters=(earlier, ChapterMaterial("c1", "中", 1, 1, "过渡。"), planted),
        foreshadowing=(
            ForeshadowMaterial(
                "f1",
                "钥匙",
                "planned",
                "c2",
                "c0",
                "钥匙还在。",
                reader_revealed_text="序章",
                event_time_text="第3天",
                character_discovered_text="第1天",
            ),
        ),
    )
    classes = {item.rule_id: item.finding_class for item in payoff}
    assert classes["foreshadow.payoff_before_plant"] == "deterministic"
    assert classes["foreshadow.reader_before_plant"] == "suspected"
    assert classes["foreshadow.discover_before_event"] == "suspected"

    hidden_chapters = tuple(
        ChapterMaterial(
            f"c{index}",
            f"第{index}章",
            index,
            1,
            "城门暗线出现了。" if index == 0 else "普通的一天。",
        )
        for index in range(4)
    )
    hidden = run_rules(
        _blank(
            chapters=hidden_chapters,
            arcs=(ArcMaterial("a1", "城门暗线", "confirmed", "hidden", "城门下的旧案"),),
        )
    )
    assert _class(hidden, "arc.hidden_quiet") == "creative_risk"


def _class(found: list[QualityFinding], rule_id: str) -> str:
    matched = [item for item in found if item.rule_id == rule_id]
    assert len(matched) == 1
    return matched[0].finding_class


def _rules(**kwargs: object) -> list[QualityFinding]:
    if "chapters" not in kwargs:
        kwargs["chapters"] = _chapters(1)
    return run_rules(_blank(**kwargs))


def _blank(**kwargs: object) -> QualityMaterials:
    payload: dict[str, object] = {
        "chapters": (),
        "events": (),
        "states": (),
        "relations": (),
        "outlines": (),
        "scenes": (),
        "foreshadowing": (),
        "entities": (),
    }
    payload.update(kwargs)
    return QualityMaterials(**payload)  # type: ignore[arg-type]


def _chapters(count: int) -> tuple[ChapterMaterial, ...]:
    return tuple(
        ChapterMaterial(f"c{index + 1}", f"第{index + 1}章", index, 1, "正文。")
        for index in range(count)
    )


def _chapter(
    client: TestClient, title: str, text: str
) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": title})
    assert novel.status_code == 201, novel.text
    created = client.post(
        f"/api/v1/novels/{novel.json()['id']}/chapters",
        json={"title": "第一章"},
    )
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
    novel_body = novel.json()
    chapter_body = saved.json()
    assert isinstance(novel_body, dict)
    assert isinstance(chapter_body, dict)
    return novel_body, chapter_body


def _analyze(client: TestClient, chapter: dict[str, object], *, scope: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": chapter["revision"], "use_mock": False, "scope": scope},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _entity(client: TestClient, novel_id: str, entity_type: str, name: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": entity_type, "name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _model(client: TestClient, name: str, model_name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/settings/models",
        json={
            "display_name": name,
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": model_name,
            "api_key": "plain-secret-key-zz99",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _text(chapter: dict[str, object]) -> str:
    content = chapter["content"]
    assert isinstance(content, dict)
    blocks = content["content"]
    assert isinstance(blocks, list)
    first = blocks[0]
    assert isinstance(first, dict)
    pieces = first["content"]
    assert isinstance(pieces, list)
    piece = pieces[0]
    assert isinstance(piece, dict)
    text = piece["text"]
    assert isinstance(text, str)
    return text
