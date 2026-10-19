"""E6 novel packages: export, preview, import, and backup hint."""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Novel
from app.models.memory import ChapterSummary, MemoryChangeProposal, StoryEvent
from app.services.portable import strip_secrets

SECRET = "sk-portable-test-key-should-not-leak"
PASSWORD = "local-access-password-should-not-leak"


def _paragraph(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _save(client: TestClient, chapter_id: str, revision: int, text: str) -> dict[str, object]:
    saved = client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={
            "revision": revision,
            "content": _paragraph(text),
            "content_format": "tiptap_json",
            "save_kind": "manual",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert isinstance(body, dict)
    return body


def _zip(blob: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(blob))


def _json_member(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    payload = json.loads(archive.read(name))
    assert isinstance(payload, dict)
    return payload


def _titles(markdown: str) -> list[str]:
    return [
        line.removeprefix("### ").strip()
        for line in markdown.splitlines()
        if line.startswith("### ")
    ]


def test_strip_secrets_removes_key_names_and_keeps_prose() -> None:
    cleaned = strip_secrets(
        {
            "title": "城门",
            "api_key": SECRET,
            "secret_ref": "ciphertext",
            "nested": {"password": PASSWORD, "note": "城门在雨里开了。"},
            "items": [{"access_token": "tok"}, "正文"],
        }
    )
    assert cleaned == {
        "title": "城门",
        "nested": {"note": "城门在雨里开了。"},
        "items": [{}, "正文"],
    }


def test_backup_latest_success_is_null_before_any_backup(auth_client: TestClient) -> None:
    listed = auth_client.get("/api/v1/admin/backups")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []
    assert listed.json()["latest_success_at"] is None


def test_portable_routes_require_session(client: TestClient) -> None:
    preview = client.post(
        "/api/v1/novels/import/preview",
        files={"file": ("book.novelpack.zip", b"not-a-zip", "application/zip")},
    )
    exported = client.post("/api/v1/novels/missing/portable-export")
    imported = client.post(
        "/api/v1/novels/import",
        files={"file": ("book.novelpack.zip", b"not-a-zip", "application/zip")},
    )
    assert preview.status_code == 401
    assert exported.status_code == 401
    assert imported.status_code == 401


def test_round_trip_imports_a_new_novel_without_overwriting(auth_client: TestClient) -> None:
    novel = auth_client.post(
        "/api/v1/novels",
        json={"title": "可携带的城", "synopsis": "雨夜", "style_guide": "短句"},
    ).json()
    other = auth_client.post("/api/v1/novels", json={"title": "另一座城"}).json()
    outsider = auth_client.post(
        f"/api/v1/novels/{other['id']}/entities",
        json={
            "entity_type": "character",
            "name": "旁观者",
            "profile": {"summary": "不该出现"},
        },
    )
    assert outsider.status_code == 201, outsider.text

    later = auth_client.post(f"/api/v1/novels/{novel['id']}/volumes", json={"title": "下卷"}).json()
    earlier = auth_client.post(
        f"/api/v1/novels/{novel['id']}/volumes", json={"title": "上卷"}
    ).json()
    reordered = auth_client.post(
        "/api/v1/volumes/reorder",
        json={"novel_id": novel["id"], "volume_ids": [earlier["id"], later["id"]]},
    )
    assert reordered.status_code == 200, reordered.text

    preface = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "序章"},
    ).json()
    first = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章", "volume_id": earlier["id"]},
    ).json()
    second = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第二章", "volume_id": later["id"]},
    ).json()
    preface = _save(auth_client, preface["id"], preface["revision"], "序章里下了雨。。")
    first = _save(auth_client, first["id"], first["revision"], "城门在雨里开了。")

    character = auth_client.post(
        f"/api/v1/novels/{novel['id']}/entities",
        json={"entity_type": "character", "name": "林晚", "profile": {"summary": "守城"}},
    ).json()
    place = auth_client.post(
        f"/api/v1/novels/{novel['id']}/entities",
        json={"entity_type": "location", "name": "城门", "profile": {"summary": "南门"}},
    ).json()
    state = auth_client.post(
        f"/api/v1/entities/{character['id']}/states",
        json={
            "chapter_id": first["id"],
            "state_data": {"summary": "左臂旧伤"},
            "evidence_quote": "城门在雨里开了。",
        },
    )
    assert state.status_code == 201, state.text
    relation = auth_client.post(
        f"/api/v1/novels/{novel['id']}/relations",
        json={
            "from_entity_id": character["id"],
            "to_entity_id": place["id"],
            "relation_type": "驻守",
            "storyline": "主线",
            "source_chapter_id": first["id"],
            "evidence_quote": "城门在雨里开了。",
        },
    )
    assert relation.status_code == 201, relation.text
    plan = auth_client.put(
        f"/api/v1/novels/{novel['id']}/story-plan",
        json={"logline": "雨夜入城", "body": "全书先写城门"},
    )
    assert plan.status_code == 200, plan.text
    outline = auth_client.put(
        f"/api/v1/chapters/{first['id']}/outline",
        json={"goal": "林晚必须入城", "forbidden_reveals": "不要写出结局"},
    )
    assert outline.status_code == 200, outline.text
    scene = auth_client.post(
        f"/api/v1/chapters/{first['id']}/scenes",
        json={
            "goal": "推开城门",
            "location_entity_id": place["id"],
            "character_entity_ids": [character["id"]],
            "turning_point": "门开了",
        },
    )
    assert scene.status_code == 201, scene.text
    foreshadow = auth_client.post(
        f"/api/v1/novels/{novel['id']}/foreshadowing",
        json={
            "introduced_chapter_id": first["id"],
            "description": "旧伤还会再疼",
            "evidence_quote": "城门在雨里开了。",
        },
    )
    assert foreshadow.status_code == 201, foreshadow.text
    goal = auth_client.put(
        f"/api/v1/novels/{novel['id']}/writing-goal", json={"target_words": 1000}
    )
    assert goal.status_code == 200, goal.text
    checked = auth_client.post(f"/api/v1/novels/{novel['id']}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    issue = next(
        item for item in checked.json()["issues"] if item["rule_id"] == "text.repeated_punctuation"
    )
    repairs = auth_client.post(f"/api/v1/quality-issues/{issue['id']}/repairs", json={})
    assert repairs.status_code == 200, repairs.text
    model = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "可携带模型",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "demo-model",
            "api_key": SECRET,
        },
    )
    assert model.status_code == 201, model.text
    secret_ref = _insert_rows(
        novel_id=novel["id"],
        chapter_id=first["id"],
        entity_id=character["id"],
        model_id=model.json()["id"],
        source_revision=first["revision"],
    )

    exported = auth_client.post(f"/api/v1/novels/{novel['id']}/portable-export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/zip")
    blob = exported.content
    archive = _zip(blob)
    decoded = "\n".join(archive.read(name).decode() for name in archive.namelist())
    assert SECRET not in decoded
    assert PASSWORD not in decoded
    assert secret_ref not in decoded
    assert "secret_ref" not in decoded
    assert "城门在雨里开了。" in decoded
    assert "雨夜入城" in decoded

    manifest = _json_member(archive, "manifest.json")
    assert manifest["format"] == "ai-novel-writer-portable-v1"
    assert manifest["format_version"] == 1
    toc = _json_member(archive, "manuscript/toc.json")
    entries = toc["entries"]
    assert isinstance(entries, list)
    titles = [entry["title"] for entry in entries if isinstance(entry, dict)]
    assert titles == ["序章", "第一章", "第二章"]
    assert "序章里下了雨" in archive.read("manuscript/0001.md").decode()
    assert "城门在雨里开了。" in archive.read("manuscript/0002.md").decode()
    assert archive.read("manuscript/0002.txt").decode().startswith("城门在雨里开了。")
    ai_doc = _json_member(archive, "ai.json")
    configs = ai_doc["model_configs"]
    assert isinstance(configs, list) and configs
    assert configs[0]["api_key_included"] is False
    assert configs[0]["reconfigure_required"] is True
    assert "api_key" not in configs[0]
    parameters = configs[0]["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["temperature"] == 0.2
    assert "api_key" not in parameters

    reading = auth_client.post(f"/api/v1/novels/{novel['id']}/export", json={"format": "markdown"})
    assert reading.status_code == 200, reading.text
    assert reading.headers["content-type"].startswith("text/markdown")
    assert _titles(reading.text) == titles
    assert "雨夜入城" not in reading.text
    assert "城门在雨里开了。" in reading.text

    before = auth_client.get("/api/v1/novels").json()
    preview = auth_client.post(
        "/api/v1/novels/import/preview",
        files={"file": ("可携带的城.novelpack.zip", blob, "application/zip")},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["can_import"] is True, preview_body["invalid_reasons"]
    assert preview_body["conflicts"]["novels"] == 1
    assert preview_body["conflicts"]["chapters"] >= 1
    assert preview_body["skipped"]["model_configs"] == 1
    assert preview_body["invalid"]["chapters"] == 0
    assert preview_body["created"]["chapters"] == 3
    assert "不会覆盖" in preview_body["message"]
    assert novel["id"] in preview_body["conflict_map"]
    assert auth_client.get("/api/v1/novels").json() == before

    imported = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("可携带的城.novelpack.zip", blob, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["novel"]
    assert copy["id"] != novel["id"]
    assert copy["title"] == "可携带的城"
    mapped = imported.json()["preview"]["conflict_map"][novel["id"]]
    assert mapped == copy["id"]
    assert preview_body["conflict_map"][novel["id"]] != novel["id"]

    original = auth_client.get(f"/api/v1/novels/{novel['id']}")
    assert original.status_code == 200
    assert original.json()["title"] == "可携带的城"
    original_chapter = auth_client.get(f"/api/v1/chapters/{first['id']}")
    assert original_chapter.json()["content"] == _paragraph("城门在雨里开了。")
    assert original_chapter.json()["revision"] == first["revision"]

    copied_export = auth_client.post(f"/api/v1/novels/{copy['id']}/portable-export")
    copied_toc = _json_member(_zip(copied_export.content), "manuscript/toc.json")
    copied_entries = copied_toc["entries"]
    assert [entry["title"] for entry in copied_entries if isinstance(entry, dict)] == titles
    assert "城门在雨里开了。" in _zip(copied_export.content).read("manuscript/0002.md").decode()

    copied_chapters = auth_client.get(f"/api/v1/novels/{copy['id']}/chapters").json()
    by_title = {item["title"]: item for item in copied_chapters}
    assert by_title["第一章"]["revision"] == first["revision"]
    assert by_title["第二章"]["revision"] == second["revision"]
    assert by_title["第一章"]["id"] != first["id"]
    full = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}").json()
    assert full["content"] == _paragraph("城门在雨里开了。")
    versions = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}/versions").json()
    assert any(item["change_source"] == "manual" for item in versions)
    fresh_versions = auth_client.get(f"/api/v1/chapters/{by_title['第二章']['id']}/versions").json()
    assert len(fresh_versions) == 1
    assert fresh_versions[0]["change_source"] == "import"
    assert fresh_versions[0]["revision"] == second["revision"]
    conflict = auth_client.put(
        f"/api/v1/chapters/{by_title['第一章']['id']}",
        json={
            "revision": full["revision"] - 1,
            "content": _paragraph("不该覆盖"),
            "content_format": "tiptap_json",
            "save_kind": "manual",
        },
    )
    assert conflict.status_code == 409
    saved = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}").json()
    assert saved["content"] == full["content"]

    copied_entities = auth_client.get(f"/api/v1/novels/{copy['id']}/entities").json()
    names = {item["name"] for item in copied_entities}
    assert names == {"林晚", "城门"}
    copied_character = next(item for item in copied_entities if item["name"] == "林晚")
    assert copied_character["id"] != character["id"]
    assert copied_character["novel_id"] == copy["id"]
    assert copied_character["states"][0]["state_data"]["summary"] == "左臂旧伤"
    copied_place = next(item for item in copied_entities if item["name"] == "城门")
    relations = auth_client.get(f"/api/v1/novels/{copy['id']}/relations").json()
    assert relations[0]["from_entity_id"] == copied_character["id"]
    assert relations[0]["to_entity_id"] == copied_place["id"]
    assert relations[0]["novel_id"] == copy["id"]
    scenes = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}/scenes").json()
    assert scenes[0]["goal"] == "推开城门"
    assert scenes[0]["location_entity_id"] == copied_place["id"]
    assert scenes[0]["character_entity_ids"] == [copied_character["id"]]
    copied_plan = auth_client.get(f"/api/v1/novels/{copy['id']}/story-plan").json()
    assert copied_plan["plan"]["logline"] == "雨夜入城"
    copied_outline = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}/outline").json()
    assert copied_outline["outline"]["goal"] == "林晚必须入城"
    hooks = auth_client.get(f"/api/v1/novels/{copy['id']}/foreshadowing").json()
    assert hooks[0]["description"] == "旧伤还会再疼"
    assert hooks[0]["introduced_chapter_id"] == by_title["第一章"]["id"]
    events = auth_client.get(f"/api/v1/novels/{copy['id']}/events").json()
    assert events[0]["description"] == "城门打开"
    assert events[0]["participants"] == [copied_character["id"]]
    summaries = auth_client.get(f"/api/v1/novels/{copy['id']}/chapter-summaries").json()
    assert summaries[0]["summary"] == "雨夜里的城门"
    proposals = auth_client.get(f"/api/v1/novels/{copy['id']}/memory-proposals").json()
    assert proposals[0]["applied_entity_id"] == copied_character["id"]
    assert proposals[0]["source_chapter_id"] == by_title["第一章"]["id"]
    issues = auth_client.get(f"/api/v1/novels/{copy['id']}/quality-issues").json()
    assert any(item["rule_id"] == "text.repeated_punctuation" for item in issues)
    assert auth_client.get(f"/api/v1/novels/{other['id']}/entities").json()[0]["name"] == "旁观者"
    assert auth_client.get(f"/api/v1/novels/{novel['id']}/events").json()[0]["participants"] == [
        character["id"]
    ]

    again = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("可携带的城.novelpack.zip", blob, "application/zip")},
    )
    assert again.status_code == 201, again.text
    third = again.json()["novel"]
    assert third["id"] not in {novel["id"], copy["id"]}
    assert auth_client.get(f"/api/v1/chapters/{first['id']}").json()["content"] == _paragraph(
        "城门在雨里开了。"
    )
    still = auth_client.get(f"/api/v1/chapters/{by_title['第一章']['id']}").json()
    assert still["content"] == full["content"]


def test_unsupported_version_and_invalid_rows_write_nothing(auth_client: TestClient) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "待校验"}).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters", json={"title": "仅有一章"}
    ).json()
    _save(auth_client, chapter["id"], chapter["revision"], "一句完整的话。")
    exported = auth_client.post(f"/api/v1/novels/{novel['id']}/portable-export")
    assert exported.status_code == 200, exported.text
    blob = exported.content
    before = [item["id"] for item in auth_client.get("/api/v1/novels").json()]

    unsupported = _rewrite_manifest(blob, 2)
    preview = auth_client.post(
        "/api/v1/novels/import/preview",
        files={"file": ("bad.novelpack.zip", unsupported, "application/zip")},
    )
    assert preview.status_code == 422, preview.text
    assert preview.json()["error"]["code"] == "UNSUPPORTED_PACKAGE"
    assert "不支持的作品包格式版本：2" in preview.json()["error"]["message"]
    assert "没有写入" in preview.json()["error"]["message"]
    refused = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("bad.novelpack.zip", unsupported, "application/zip")},
    )
    assert refused.status_code == 422
    assert [item["id"] for item in auth_client.get("/api/v1/novels").json()] == before

    invalid = _blank_chapter_title(blob)
    invalid_preview = auth_client.post(
        "/api/v1/novels/import/preview",
        files={"file": ("invalid.novelpack.zip", invalid, "application/zip")},
    )
    assert invalid_preview.status_code == 200, invalid_preview.text
    assert invalid_preview.json()["can_import"] is False
    assert invalid_preview.json()["invalid"]["chapters"] >= 1
    assert "没有写入" in invalid_preview.json()["message"]
    invalid_import = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("invalid.novelpack.zip", invalid, "application/zip")},
    )
    assert invalid_import.status_code == 422
    assert invalid_import.json()["error"]["code"] == "PACKAGE_INVALID"
    assert [item["id"] for item in auth_client.get("/api/v1/novels").json()] == before
    assert auth_client.get(f"/api/v1/novels/{novel['id']}").json()["title"] == "待校验"


def test_import_failure_leaves_no_partial_novel(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = auth_client.post("/api/v1/novels", json={"title": "回滚样本"}).json()
    exported = auth_client.post(f"/api/v1/novels/{novel['id']}/portable-export")
    blob = exported.content
    before = [item["id"] for item in auth_client.get("/api/v1/novels").json()]

    def explode(session: object, plan: object) -> Novel:
        del plan
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        now = datetime.now(UTC)
        partial = Novel(
            id=str(uuid.uuid4()),
            title="半成品不该留下",
            genre=None,
            synopsis=None,
            style_guide=None,
            status="draft",
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        session.add(partial)
        session.flush()
        raise RuntimeError("disk")

    monkeypatch.setattr("app.services.portable._write_plan", explode)
    failed = auth_client.post(
        "/api/v1/novels/import",
        files={"file": ("rollback.novelpack.zip", blob, "application/zip")},
    )
    assert failed.status_code == 500, failed.text
    assert failed.json()["error"]["code"] == "PACKAGE_IMPORT_FAILED"
    assert "半成品" in failed.json()["error"]["message"]
    ids = [item["id"] for item in auth_client.get("/api/v1/novels").json()]
    assert ids == before
    assert auth_client.get(f"/api/v1/novels/{novel['id']}").json()["title"] == "回滚样本"


def _insert_rows(
    *,
    novel_id: str,
    chapter_id: str,
    entity_id: str,
    model_id: str,
    source_revision: int,
) -> str:
    engine = build_engine(get_settings().resolved_database_url)
    factory = build_session_factory(engine)
    now = datetime.now(UTC)
    with factory() as session:
        config = session.get(ModelConfig, model_id)
        assert config is not None and config.secret_ref
        secret_ref = config.secret_ref
        parameters = dict(config.parameters)
        parameters["api_key"] = SECRET
        parameters["temperature"] = 0.2
        config.parameters = parameters
        session.add(
            StoryEvent(
                id=str(uuid.uuid4()),
                novel_id=novel_id,
                chapter_id=chapter_id,
                source_revision=source_revision,
                proposal_id=None,
                event_time_text="雨夜",
                description="城门打开",
                participants=[entity_id],
                evidence_quote="城门在雨里开了。",
                certainty="confirmed",
                created_at=now,
                deleted_at=None,
            )
        )
        session.add(
            ChapterSummary(
                id=str(uuid.uuid4()),
                chapter_id=chapter_id,
                summary="雨夜里的城门",
                key_facts=["城门开了"],
                source_revision=source_revision,
                model_name=None,
                status="current",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MemoryChangeProposal(
                id=str(uuid.uuid4()),
                novel_id=novel_id,
                source_chapter_id=chapter_id,
                source_revision=source_revision,
                proposal_type="entity_update",
                payload={"applied": {"entity_id": entity_id}, "name": "林晚"},
                evidence_quote="城门在雨里开了。",
                certainty="inferred",
                status="pending",
                review_note=None,
                created_at=now,
                reviewed_at=None,
            )
        )
        session.add(
            AiTask(
                id=str(uuid.uuid4()),
                novel_id=novel_id,
                chapter_id=chapter_id,
                task_type="continue",
                status="completed",
                model_config_id=model_id,
                input_snapshot={
                    "instruction": "续写城门",
                    "chapter_text": "城门在雨里开了。",
                    "api_key": SECRET,
                    "password": PASSWORD,
                    "provider_mode": "mock",
                    "model_name": "demo-model",
                },
                prompt_version="continue_v1",
                output_text="门开了。",
                error_code=None,
                error_message_safe=None,
                input_tokens=None,
                output_tokens=None,
                resolution=None,
                started_at=now,
                finished_at=now,
                created_at=now,
            )
        )
        session.commit()
    engine.dispose()
    return secret_ref


def _rewrite_manifest(blob: bytes, version: int) -> bytes:
    return _replace_member(
        blob,
        "manifest.json",
        lambda payload: {**payload, "format_version": version},
    )


def _blank_chapter_title(blob: bytes) -> bytes:
    def edit(payload: dict[str, object]) -> dict[str, object]:
        chapters = payload["chapters"]
        assert isinstance(chapters, list) and isinstance(chapters[0], dict)
        chapters[0]["title"] = ""
        return payload

    return _replace_member(blob, "catalog.json", edit)


def _replace_member(blob: bytes, name: str, edit: object) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(blob))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            raw = source.read(info.filename)
            if info.filename == name:
                payload = json.loads(raw)
                assert isinstance(payload, dict)
                editor = cast("callable[[dict[str, object]], dict[str, object]]", edit)
                raw = (json.dumps(editor(payload), ensure_ascii=False, indent=2) + "\n").encode()
            target.writestr(info.filename, raw)
    return buffer.getvalue()
