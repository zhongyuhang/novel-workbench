"""Resume must not insert a second empty chapter with the same title."""

from fastapi.testclient import TestClient

from app.core.content import document_to_text
from app.services.chapter_shells import (
    ShellChapter,
    duplicate_shell_ids,
    next_numbered_title,
    reusable_shell_id,
    title_for_new_chapter,
)


def test_next_title_comes_from_the_server_list_not_a_local_counter() -> None:
    titles = [f"第{index}章" for index in range(1, 19)]
    assert next_numbered_title(titles) == "第19章"
    assert title_for_new_chapter([(title, 4000) for title in titles]) == "第19章"
    # A stale counter that still says 19 must ask for the shell that is already there.
    with_shell = [*titles, "第19章"]
    assert title_for_new_chapter([(title, 4000) for title in titles] + [("第19章", 26)]) == "第19章"
    assert next_numbered_title(with_shell) == "第20章"


def test_same_title_shell_is_reused_and_a_full_chapter_is_not() -> None:
    shell = ShellChapter(id="shell", title="第19章", word_count=26, sort_order=18, volume_id=None)
    full = ShellChapter(id="full", title="第19章", word_count=4707, sort_order=19, volume_id=None)
    assert reusable_shell_id([full, shell], "第19章", None) == "shell"
    assert reusable_shell_id([full], "第19章", None) is None
    spaced = ShellChapter(
        id="spaced",
        title="第 19 章",
        word_count=0,
        sort_order=18,
        volume_id=None,
    )
    assert reusable_shell_id([spaced], "第19章", None) == "spaced"


def test_create_reuses_a_near_empty_chapter_instead_of_duplicating_it(
    auth_client: TestClient,
) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "续跑"}).json()
    first = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第19章"},
    )
    assert first.status_code == 201, first.text
    saved = auth_client.put(
        f"/api/v1/chapters/{first.json()['id']}",
        json={
            "revision": first.json()["revision"],
            "save_kind": "manual",
            "content": _doc("夜色刚落，桥还没写完。"),
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["word_count"] <= 40

    again = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第19章"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/chapters")
    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()] == ["第19章"]

    full = auth_client.put(
        f"/api/v1/chapters/{first.json()['id']}",
        json={
            "revision": again.json()["revision"],
            "save_kind": "manual",
            "content": _doc("夜色" * 80),
        },
    )
    assert full.status_code == 200, full.text
    second = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第19章"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]
    assert document_to_text(full.json()["content"]).startswith("夜色")


def test_cleanup_removes_duplicate_shells_and_keeps_the_written_chapter(
    auth_client: TestClient,
) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "空壳"}).json()
    shell = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第19章"},
    ).json()
    # The second insert is a different title so create does not reuse the shell.
    other = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第19章·正文"},
    ).json()
    written = auth_client.put(
        f"/api/v1/chapters/{other['id']}",
        json={
            "revision": other["revision"],
            "save_kind": "manual",
            "title": "第19章",
            "content": _doc("夜色" * 80),
        },
    )
    assert written.status_code == 200, written.text
    listed = auth_client.get(f"/api/v1/novels/{novel['id']}/chapters").json()
    assert len(listed) == 2

    cleaned = auth_client.post(f"/api/v1/novels/{novel['id']}/chapters/cleanup-shells")
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["deleted"] == 1
    after = auth_client.get(f"/api/v1/novels/{novel['id']}/chapters").json()
    assert [item["id"] for item in after] == [written.json()["id"]]
    assert shell["id"] not in {item["id"] for item in after}
    again = auth_client.post(f"/api/v1/novels/{novel['id']}/chapters/cleanup-shells")
    assert again.json()["deleted"] == 0


def test_duplicate_shell_ids_keep_one_empty_draft() -> None:
    first = ShellChapter(id="a", title="未命名章节", word_count=0, sort_order=0, volume_id=None)
    second = ShellChapter(id="b", title="未命名章节", word_count=0, sort_order=1, volume_id=None)
    assert duplicate_shell_ids([first, second]) == ["a"]
    assert duplicate_shell_ids([first]) == []


def _doc(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }
