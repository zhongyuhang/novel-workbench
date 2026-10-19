"""Story plan, chapter outlines, and scene cards."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.services.planning import planning_counts_as_fact

PARAGRAPH = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "没有大纲也能写的正文"}]}
    ],
}


def test_planning_requires_session(client: TestClient) -> None:
    story = client.get("/api/v1/novels/missing/story-plan")
    scenes = client.post("/api/v1/chapters/missing/scenes", json={"goal": "夜谈"})

    assert story.status_code == 401
    assert scenes.status_code == 401
    assert story.json()["error"]["code"] == "UNAUTHENTICATED"
    assert "traceback" not in story.text.lower()


def test_story_plan_chapter_outline_and_scene_reorder(auth_client: TestClient) -> None:
    novel_id, chapter_id, chapter_revision = _novel_and_chapter(auth_client)
    empty = auth_client.get(f"/api/v1/novels/{novel_id}/story-plan")
    assert empty.status_code == 200, empty.text
    assert empty.json()["plan"] is None

    created = auth_client.put(
        f"/api/v1/novels/{novel_id}/story-plan",
        json={
            "logline": "一个人把城门关早了",
            "body": "上卷找钥匙，下卷开门",
            "ending_intent": "门开了，城里已经空了",
        },
    )
    assert created.status_code == 200, created.text
    plan = created.json()
    assert plan["status"] == "draft"
    assert plan["revision"] == 1
    assert plan["counts_as_fact"] is False
    assert planning_counts_as_fact("draft") is False
    assert planning_counts_as_fact("confirmed") is True

    confirmed = auth_client.post(
        f"/api/v1/novels/{novel_id}/story-plan/confirm",
        json={"expected_revision": plan["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["counts_as_fact"] is True
    assert confirmed.json()["revision"] == 2

    edited = auth_client.put(
        f"/api/v1/novels/{novel_id}/story-plan",
        json={
            "body": "上卷找钥匙，中卷迷路，下卷开门",
            "expected_revision": confirmed.json()["revision"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "draft"
    assert edited.json()["counts_as_fact"] is False
    assert edited.json()["logline"] == "一个人把城门关早了"

    stale = auth_client.put(
        f"/api/v1/novels/{novel_id}/story-plan",
        json={"status": "stale", "expected_revision": edited.json()["revision"]},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["status"] == "stale"
    assert stale.json()["counts_as_fact"] is False

    outline = auth_client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={
            "goal": "让读者知道城门关早了",
            "must_advance": "主角发现钥匙不在原处",
            "required_events": "守门人提起昨夜的钟声",
            "allowed_reveals": "可以写出钟是坏的",
            "forbidden_reveals": "不能写出城里已经空了",
            "target_words": 1800,
            "ending_hook": "钥匙孔是温的",
        },
    )
    assert outline.status_code == 200, outline.text
    assert outline.json()["status"] == "draft"
    assert outline.json()["counts_as_fact"] is False
    assert outline.json()["novel_id"] == novel_id
    chapter_after = auth_client.get(f"/api/v1/chapters/{chapter_id}")
    assert chapter_after.json()["revision"] == chapter_revision

    forced = auth_client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={"goal": "直接确认", "status": "confirmed", "expected_revision": 1},
    )
    assert forced.status_code == 422

    conflict = auth_client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={"goal": "旧修订", "expected_revision": 99},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"

    confirmed_outline = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/outline/confirm",
        json={"expected_revision": outline.json()["revision"]},
    )
    assert confirmed_outline.status_code == 200, confirmed_outline.text
    assert confirmed_outline.json()["counts_as_fact"] is True

    place_id, person_id = _place_and_person(auth_client, novel_id)
    first = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes",
        json={
            "goal": "在城门前问钟",
            "location_entity_id": place_id,
            "character_entity_ids": [person_id],
            "conflict": "守门人不让靠近",
            "turning_point": "钟自己响了",
            "expected_outcome": "主角记下钟声",
            "must_convey": "钟是坏的",
            "must_not_reveal": "城里没人",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["sort_order"] == 0
    assert first.json()["status"] == "draft"
    assert first.json()["counts_as_fact"] is False
    assert first.json()["location"]["name"] == "南门"
    assert first.json()["location"]["available"] is True
    assert first.json()["characters"][0]["name"] == "守门人"
    assert "profile" not in first.text

    second = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes",
        json={"goal": "回到钥匙孔", "status": "confirmed"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["counts_as_fact"] is True
    third = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes",
        json={"goal": "听见第二声"},
    )
    assert third.status_code == 201, third.text

    reordered = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes/reorder",
        json={
            "scene_ids": [
                third.json()["id"],
                first.json()["id"],
                second.json()["id"],
            ]
        },
    )
    assert reordered.status_code == 200, reordered.text
    assert [item["goal"] for item in reordered.json()] == [
        "听见第二声",
        "在城门前问钟",
        "回到钥匙孔",
    ]
    listed = auth_client.get(f"/api/v1/chapters/{chapter_id}/scenes")
    assert [item["sort_order"] for item in listed.json()] == [0, 1, 2]
    assert [item["goal"] for item in listed.json()] == [
        "听见第二声",
        "在城门前问钟",
        "回到钥匙孔",
    ]

    partial = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes/reorder",
        json={"scene_ids": [first.json()["id"]]},
    )
    assert partial.status_code == 422
    remaining = auth_client.get(f"/api/v1/chapters/{chapter_id}/scenes").json()
    assert remaining[0]["goal"] == "听见第二声"


def test_unconfirmed_plan_is_not_a_fact_and_old_chapter_still_writes(
    auth_client: TestClient,
) -> None:
    novel_id, chapter_id, revision = _novel_and_chapter(auth_client, "自由创作")
    saved = auth_client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={
            "revision": revision,
            "title": "没有大纲的一章",
            "content": PARAGRAPH,
            "content_format": "tiptap_json",
            "save_kind": "manual",
        },
    )
    assert saved.status_code == 200, saved.text
    exported = auth_client.post(
        f"/api/v1/novels/{novel_id}/export",
        json={"format": "markdown"},
    )
    assert exported.status_code == 200, exported.text
    assert "没有大纲也能写的正文" in exported.text

    outline = auth_client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={"goal": "这份目标不该出现在导出里", "status": "archived"},
    )
    assert outline.json()["counts_as_fact"] is False
    exported_again = auth_client.post(
        f"/api/v1/novels/{novel_id}/export",
        json={"format": "txt"},
    )
    assert "没有大纲也能写的正文" in exported_again.text
    assert "这份目标不该出现在导出里" not in exported_again.text
    current = auth_client.get(f"/api/v1/chapters/{chapter_id}")
    assert current.json()["revision"] == saved.json()["revision"]
    assert current.json()["content"]["content"][0]["content"][0]["text"] == "没有大纲也能写的正文"


def test_planning_references_stay_inside_the_novel(auth_client: TestClient) -> None:
    first_novel, first_chapter, _revision = _novel_and_chapter(auth_client, "作品甲")
    second_novel, second_chapter, _other_revision = _novel_and_chapter(auth_client, "作品乙")
    place_id, person_id = _place_and_person(auth_client, first_novel)
    other_place, other_person = _place_and_person(auth_client, second_novel, "北门", "外人")

    leaked_place = auth_client.post(
        f"/api/v1/chapters/{first_chapter}/scenes",
        json={"location_entity_id": other_place},
    )
    assert leaked_place.status_code == 422
    assert leaked_place.json()["error"]["code"] == "INVALID_REFERENCE"
    leaked_person = auth_client.post(
        f"/api/v1/chapters/{first_chapter}/scenes",
        json={"character_entity_ids": [other_person]},
    )
    assert leaked_person.status_code == 422
    wrong_type = auth_client.post(
        f"/api/v1/chapters/{first_chapter}/scenes",
        json={"location_entity_id": person_id, "character_entity_ids": [place_id]},
    )
    assert wrong_type.status_code == 422

    own = auth_client.post(
        f"/api/v1/chapters/{first_chapter}/scenes",
        json={"goal": "只属于甲", "location_entity_id": place_id},
    )
    assert own.status_code == 201, own.text
    other_scene = auth_client.post(
        f"/api/v1/chapters/{second_chapter}/scenes",
        json={"goal": "只属于乙"},
    )
    mixed = auth_client.post(
        f"/api/v1/chapters/{first_chapter}/scenes/reorder",
        json={"scene_ids": [own.json()["id"], other_scene.json()["id"]]},
    )
    assert mixed.status_code == 422
    assert auth_client.get(f"/api/v1/chapters/{second_chapter}/outline").json()["outline"] is None

    outline = auth_client.put(
        f"/api/v1/chapters/{first_chapter}/outline",
        json={"goal": "甲的章节目标"},
    )
    assert outline.status_code == 200, outline.text
    listed = auth_client.get(f"/api/v1/novels/{second_novel}/chapter-outlines")
    assert listed.status_code == 200, listed.text
    assert listed.json() == []
    assert auth_client.get(f"/api/v1/novels/{first_novel}/chapter-outlines").json()[0]["goal"] == (
        "甲的章节目标"
    )


def test_delete_and_move_keep_planning_rows_on_the_same_novel(auth_client: TestClient) -> None:
    novel_id, chapter_id, _revision = _novel_and_chapter(auth_client, "要挪的作品")
    volume = auth_client.post(
        f"/api/v1/novels/{novel_id}/volumes",
        json={"title": "卷二"},
    ).json()
    outline = auth_client.put(
        f"/api/v1/chapters/{chapter_id}/outline",
        json={"goal": "跟着章节走"},
    )
    scene = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/scenes",
        json={"goal": "跟着章节的场景"},
    )
    assert outline.status_code == 200, outline.text
    assert scene.status_code == 201, scene.text

    moved = auth_client.post(
        f"/api/v1/chapters/{chapter_id}/move",
        json={"volume_id": volume["id"], "sort_order": 0},
    )
    assert moved.status_code == 200, moved.text
    still = auth_client.get(f"/api/v1/chapters/{chapter_id}/outline")
    assert still.json()["outline"]["novel_id"] == novel_id
    assert still.json()["outline"]["chapter_id"] == chapter_id
    scenes = auth_client.get(f"/api/v1/chapters/{chapter_id}/scenes")
    assert scenes.json()[0]["novel_id"] == novel_id

    copy = auth_client.post(f"/api/v1/chapters/{chapter_id}/duplicate")
    assert copy.status_code == 201, copy.text
    copied_outline = auth_client.get(f"/api/v1/chapters/{copy.json()['id']}/outline")
    assert copied_outline.json()["outline"] is None
    assert auth_client.get(f"/api/v1/chapters/{chapter_id}/outline").json()["outline"]["goal"] == (
        "跟着章节走"
    )

    removed = auth_client.delete(f"/api/v1/chapters/{chapter_id}")
    assert removed.status_code == 204, removed.text
    hidden = auth_client.get(f"/api/v1/chapters/{chapter_id}/outline")
    assert hidden.status_code == 404
    hidden_scene = auth_client.get(f"/api/v1/chapters/{chapter_id}/scenes")
    assert hidden_scene.status_code == 404

    engine = create_engine(get_settings().resolved_database_url)
    with engine.connect() as connection:
        outline_row = connection.execute(
            text("SELECT novel_id, chapter_id, goal FROM chapter_outlines")
        ).one()
        scene_row = connection.execute(
            text("SELECT novel_id, chapter_id, goal FROM scene_cards")
        ).one()
        chapter_row = connection.execute(
            text("SELECT novel_id, deleted_at FROM chapters WHERE id = :chapter_id"),
            {"chapter_id": chapter_id},
        ).one()
    engine.dispose()
    assert outline_row == (novel_id, chapter_id, "跟着章节走")
    assert scene_row == (novel_id, chapter_id, "跟着章节的场景")
    assert chapter_row[0] == novel_id
    assert chapter_row[1] is not None


def _novel_and_chapter(
    auth_client: TestClient,
    title: str = "规划作品",
) -> tuple[str, str, int]:
    novel = auth_client.post("/api/v1/novels", json={"title": title})
    assert novel.status_code == 201, novel.text
    chapter = auth_client.post(
        f"/api/v1/novels/{novel.json()['id']}/chapters",
        json={"title": "第一章"},
    )
    assert chapter.status_code == 201, chapter.text
    return novel.json()["id"], chapter.json()["id"], chapter.json()["revision"]


def _place_and_person(
    auth_client: TestClient,
    novel_id: str,
    place_name: str = "南门",
    person_name: str = "守门人",
) -> tuple[str, str]:
    place = auth_client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": "location", "name": place_name, "profile": {"summary": "砖墙"}},
    )
    person = auth_client.post(
        f"/api/v1/novels/{novel_id}/entities",
        json={"entity_type": "character", "name": person_name, "profile": {"summary": "值夜"}},
    )
    assert place.status_code == 201, place.text
    assert person.status_code == 201, person.text
    return place.json()["id"], person.json()["id"]
