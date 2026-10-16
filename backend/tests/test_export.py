"""Markdown and TXT export."""

from urllib.parse import quote

from fastapi.testclient import TestClient

from app.core.manuscript import document_to_markdown, document_to_plain

RICH_DOCUMENT: dict[str, object] = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "小标题"}],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "甲", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "乙"},
                {"type": "hardBreak"},
                {"type": "text", "text": "丙"},
            ],
        },
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "条目一"}]}
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "条目二"}]}
                    ],
                },
            ],
        },
        {
            "type": "image",
            "attrs": {"alt": "示意图", "src": "https://example.com/a.png"},
        },
    ],
}


def _texts(node: object) -> list[str]:
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "text" and isinstance(value.get("text"), str):
                found.append(value["text"])
            if value.get("type") == "image":
                attrs = value.get("attrs")
                if isinstance(attrs, dict) and isinstance(attrs.get("alt"), str):
                    found.append(attrs["alt"])
            content = value.get("content")
            if isinstance(content, list):
                for child in content:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return found


def test_renderers_keep_text_in_order() -> None:
    pieces = _texts(RICH_DOCUMENT)
    assert pieces == ["小标题", "甲", "乙", "丙", "条目一", "条目二", "示意图"]
    for rendered in (document_to_markdown(RICH_DOCUMENT), document_to_plain(RICH_DOCUMENT)):
        cursor = -1
        for piece in pieces:
            found = rendered.find(piece, cursor + 1)
            assert found > cursor
            cursor = found
    markdown = document_to_markdown(RICH_DOCUMENT)
    assert "**甲**" in markdown
    assert "- 条目一" in markdown
    assert "![示意图](https://example.com/a.png)" in markdown


def _paragraph(text: str, *, bold: bool = False) -> dict[str, object]:
    text_node: dict[str, object] = {"type": "text", "text": text}
    if bold:
        text_node["marks"] = [{"type": "bold"}]
    return {"type": "doc", "content": [{"type": "paragraph", "content": [text_node]}]}


def _hard_break(first: str, second: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": first},
                    {"type": "hardBreak"},
                    {"type": "text", "text": second},
                ],
            }
        ],
    }


def _save(client: TestClient, chapter_id: str, revision: int, content: dict[str, object]) -> None:
    saved = client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={"revision": revision, "content": content, "save_kind": "manual"},
    )
    assert saved.status_code == 200, saved.text


def test_t015_export_preserves_order_and_text(auth_client: TestClient) -> None:
    novel = auth_client.post(
        "/api/v1/novels",
        json={"title": "导出用小说", "synopsis": "简介句子"},
    ).json()
    later_volume = auth_client.post(
        f"/api/v1/novels/{novel['id']}/volumes",
        json={"title": "第二卷名"},
    ).json()
    earlier_volume = auth_client.post(
        f"/api/v1/novels/{novel['id']}/volumes",
        json={"title": "第一卷名"},
    ).json()
    reordered = auth_client.post(
        "/api/v1/volumes/reorder",
        json={"novel_id": novel["id"], "volume_ids": [earlier_volume["id"], later_volume["id"]]},
    )
    assert reordered.status_code == 200, reordered.text

    preface = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "序章标题"},
    ).json()
    developed = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "发展标题", "volume_id": earlier_volume["id"]},
    ).json()
    opening = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "开篇标题", "volume_id": earlier_volume["id"]},
    ).json()
    moved = auth_client.post(
        f"/api/v1/chapters/{opening['id']}/move",
        json={"volume_id": earlier_volume["id"], "sort_order": 0},
    )
    assert moved.status_code == 200, moved.text
    ending = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "终章标题", "volume_id": later_volume["id"]},
    ).json()
    discarded = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "删除标题", "volume_id": later_volume["id"]},
    ).json()

    _save(auth_client, preface["id"], preface["revision"], _paragraph("序章正文甲"))
    _save(auth_client, opening["id"], opening["revision"], _paragraph("开篇正文乙", bold=True))
    _save(
        auth_client,
        developed["id"],
        developed["revision"],
        _hard_break("发展正文丙", "发展换行丁"),
    )
    _save(auth_client, ending["id"], ending["revision"], _paragraph("终章正文戊"))
    _save(auth_client, discarded["id"], discarded["revision"], _paragraph("已删正文己"))
    deleted = auth_client.delete(f"/api/v1/chapters/{discarded['id']}")
    assert deleted.status_code == 204

    other = auth_client.post("/api/v1/novels", json={"title": "另一本"}).json()
    foreign = auth_client.post(
        f"/api/v1/novels/{other['id']}/chapters",
        json={"title": "外人"},
    ).json()
    _save(auth_client, foreign["id"], foreign["revision"], _paragraph("别的作品正文庚"))

    expected = [
        "导出用小说",
        "简介句子",
        "未分卷",
        "序章标题",
        "序章正文甲",
        "第一卷名",
        "开篇标题",
        "开篇正文乙",
        "发展标题",
        "发展正文丙",
        "发展换行丁",
        "第二卷名",
        "终章标题",
        "终章正文戊",
    ]
    absent = ["已删正文己", "删除标题", "别的作品正文庚", "另一本"]

    for export_format, media_type, extension in (
        ("markdown", "text/markdown", "md"),
        ("txt", "text/plain", "txt"),
    ):
        response = auth_client.post(
            f"/api/v1/novels/{novel['id']}/export",
            json={"format": export_format},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(media_type)
        disposition = response.headers["content-disposition"]
        assert quote(f"导出用小说.{extension}", safe="") in disposition
        body = response.text
        cursor = -1
        for piece in expected:
            found = body.find(piece, cursor + 1)
            assert found > cursor, (export_format, piece, body)
            cursor = found
        for piece in absent:
            assert piece not in body
        if export_format == "markdown":
            assert "**开篇正文乙**" in body
            assert "发展正文丙\\\n发展换行丁" in body


def test_export_rejects_bad_input(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "空导出"}).json()
    rejected = auth_client.post(
        f"/api/v1/novels/{novel['id']}/export",
        json={"format": "html"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"

    missing = auth_client.post("/api/v1/novels/missing/export", json={"format": "txt"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
