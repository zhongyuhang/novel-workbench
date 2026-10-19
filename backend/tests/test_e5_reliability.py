"""E5: accept transactions, save conflicts, SSE recovery, and version diffs."""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.ai.runner import _write_output
from app.core.config import get_settings
from app.core.content import apply_candidate_text, document_to_text, text_to_document, word_count
from app.core.errors import RevisionConflict, SelectionNotFound, TaskStateError
from app.core.text_diff import diff_lines
from app.schemas.ai import AiTaskAccept
from app.schemas.catalog import ChapterWrite
from app.services.ai_tasks import accept_ai_task
from app.services.catalog import save_chapter

SECRET = "sk-live-key-should-never-log"


def test_selection_must_be_unique_before_any_write() -> None:
    document = text_to_document("门前有树。门前有树。")
    with pytest.raises(SelectionNotFound):
        apply_candidate_text(
            document, "新树", mode="replace_selection", selection_text="没有的句子"
        )
    with pytest.raises(SelectionNotFound, match="多次"):
        apply_candidate_text(document, "新树", mode="replace_selection", selection_text="门前有树")
    with pytest.raises(SelectionNotFound, match="多次"):
        apply_candidate_text(document, "补一句", mode="insert", selection_text="门前有树")
    replaced = apply_candidate_text(
        text_to_document("门前有树。"),
        "院里有灯。",
        mode="replace_selection",
        selection_text="门前有树。",
    )
    inserted = apply_candidate_text(
        text_to_document("门前有树。"),
        "夜里起风。",
        mode="insert",
        selection_text="门前有树。",
    )
    appended = apply_candidate_text(
        text_to_document("门前有树。"),
        "夜里起风。",
        mode="append",
        selection_text="",
    )
    assert document_to_text(replaced) == "院里有灯。"
    assert document_to_text(inserted) == "门前有树。\n\n夜里起风。"
    assert document_to_text(appended) == "门前有树。\n\n夜里起风。"


def test_diff_lines_keeps_unchanged_text() -> None:
    hunks = diff_lines("第一段\n旧句子", "第一段\n新句子")
    assert [(hunk.op, hunk.text) for hunk in hunks] == [
        ("equal", "第一段"),
        ("delete", "旧句子"),
        ("insert", "新句子"),
    ]
    assert diff_lines("一样", "一样")[0].op == "equal"


def test_revision_conflicts_do_not_drop_the_newer_manuscript(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client, "冲突")
    winner = _put(auth_client, chapter["id"], int(chapter["revision"]), "先写入的正文", "manual")
    loser = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "save_kind": "autosave",
            "content": text_to_document("过期的自动保存"),
        },
    )
    assert loser.status_code == 409
    assert loser.json()["error"]["code"] == "REVISION_CONFLICT"
    assert _body(auth_client, chapter["id"]) == "先写入的正文"
    assert _revision(auth_client, chapter["id"]) == winner["revision"]
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    assert [item["change_source"] for item in versions] == ["manual", "manual"]
    assert {item["preview"] for item in versions} == {"原有正文", "先写入的正文"}
    assert all(item["ai_task_id"] is None for item in versions)

    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, winner, mock_tokens=["不该盖上去"]),
    )
    task = _wait(auth_client, created.json()["id"])
    moved = _put(auth_client, chapter["id"], int(winner["revision"]), "更新后的正文", "manual")
    stale = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": moved["revision"], "apply_mode": "append"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    assert "没有写入" in stale.json()["error"]["message"]
    assert _body(auth_client, chapter["id"]) == "更新后的正文"
    fresh = auth_client.get(f"/api/v1/ai/tasks/{task['id']}").json()
    assert fresh["resolution"] is None
    assert fresh["status"] == "completed"

    quality_novel, current = _seed(auth_client, "质量冲突")
    source = _put_new(auth_client, quality_novel["id"], "前文", "阿宁是左撇子。")
    current = _put(auth_client, current["id"], int(current["revision"]), "阿宁是右撇子。", "manual")
    _insert_event(
        novel_id=quality_novel["id"],
        chapter_id=source["id"],
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
    )
    repair = _repair_for(auth_client, quality_novel["id"], current["id"])
    newer = _put(
        auth_client,
        current["id"],
        int(repair["target_revision"]),
        "阿宁是右撇子。他没有改口。",
        "manual",
    )
    blocked = auth_client.post(
        f"/api/v1/quality-repairs/{repair['id']}/accept",
        json={"target_revision": repair["target_revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REVISION_CONFLICT"
    assert _body(auth_client, current["id"]) == "阿宁是右撇子。他没有改口。"
    assert _revision(auth_client, current["id"]) == newer["revision"]
    issue = auth_client.get(f"/api/v1/quality-issues/{repair['issue_id']}").json()
    assert issue["status"] != "fixed"
    assert issue["candidates"][0]["status"] == "conflict"


def test_accept_is_atomic_and_repeat_does_not_insert_twice(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client, "采纳")
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, task_type="continue", mock_tokens=["新的一段"]),
    )
    task = _wait(auth_client, created.json()["id"])
    accepted = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": chapter["revision"], "apply_mode": "append"},
    )
    assert accepted.status_code == 200, accepted.text
    saved = accepted.json()["chapter"]
    assert document_to_text(saved["content"]) == "原有正文\n\n新的一段"
    assert saved["word_count"] == word_count(saved["content"])
    versions = auth_client.get(f"/api/v1/chapters/{saved['id']}/versions").json()
    accepted_version = next(item for item in versions if item["change_source"] == "ai_accepted")
    assert accepted_version["ai_task_id"] == task["id"]
    assert accepted_version["repair_candidate_id"] is None

    again = auth_client.post(
        f"/api/v1/ai/tasks/{task['id']}/accept",
        json={"target_revision": saved["revision"], "apply_mode": "append"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TASK_STATE"
    assert _body(auth_client, chapter["id"]) == "原有正文\n\n新的一段"
    assert _revision(auth_client, chapter["id"]) == saved["revision"]

    missing = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, saved, selection_text="并不存在的选区", mock_tokens=["替换"]),
    )
    other = _wait(auth_client, missing.json()["id"])
    rejected = auth_client.post(
        f"/api/v1/ai/tasks/{other['id']}/accept",
        json={"target_revision": saved["revision"], "apply_mode": "replace_selection"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "SELECTION_NOT_FOUND"
    assert _body(auth_client, chapter["id"]) == "原有正文\n\n新的一段"
    assert auth_client.get(f"/api/v1/ai/tasks/{other['id']}").json()["resolution"] is None


def test_failed_snapshot_rolls_back_manual_ai_and_repair(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel, chapter = _seed(auth_client, "回滚")
    before = auth_client.get(f"/api/v1/chapters/{chapter['id']}").json()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr("app.services.catalog._add_version", boom)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        auth_client.put(
            f"/api/v1/chapters/{chapter['id']}",
            json={
                "revision": before["revision"],
                "save_kind": "manual",
                "content": text_to_document("不该留下的手动保存"),
            },
        )
    assert _body(auth_client, chapter["id"]) == "原有正文"
    assert _revision(auth_client, chapter["id"]) == before["revision"]

    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, before, mock_tokens=["不该留下"]),
    )
    task = _wait(auth_client, created.json()["id"])
    with pytest.raises(RuntimeError, match="snapshot failed"):
        auth_client.post(
            f"/api/v1/ai/tasks/{task['id']}/accept",
            json={"target_revision": before["revision"], "apply_mode": "append"},
        )
    assert _body(auth_client, chapter["id"]) == "原有正文"
    assert auth_client.get(f"/api/v1/ai/tasks/{task['id']}").json()["resolution"] is None
    kept_versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    assert [item["change_source"] for item in kept_versions] == ["manual"]
    assert "不该留下" not in _body(auth_client, chapter["id"])

    monkeypatch.undo()
    repair_chapter = _put(
        auth_client, chapter["id"], int(before["revision"]), "阿宁是右撇子。", "manual"
    )
    source = _put_new(auth_client, novel["id"], "前文", "阿宁是左撇子。")
    _insert_event(
        novel_id=novel["id"],
        chapter_id=source["id"],
        description="阿宁是左撇子",
        quote="阿宁是左撇子",
    )
    repair = _repair_for(auth_client, novel["id"], chapter["id"])
    monkeypatch.setattr("app.services.catalog._add_version", boom)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        auth_client.post(
            f"/api/v1/quality-repairs/{repair['id']}/accept",
            json={"target_revision": repair["target_revision"]},
        )
    assert "右撇子" in _body(auth_client, chapter["id"])
    assert _revision(auth_client, chapter["id"]) == repair_chapter["revision"]
    issue = auth_client.get(f"/api/v1/quality-issues/{repair['issue_id']}").json()
    assert issue["status"] != "fixed"
    assert issue["candidates"][0]["status"] == "proposed"


def test_concurrent_saves_and_accepts_keep_one_result(auth_client: TestClient) -> None:
    _novel, chapter = _seed(auth_client, "并发保存")
    factory = auth_client.app.state.session_factory
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def save(text_value: str) -> None:
        session = factory()
        try:
            barrier.wait(5)
            try:
                save_chapter(
                    session,
                    chapter["id"],
                    ChapterWrite(
                        revision=int(chapter["revision"]),
                        content=text_to_document(text_value),
                        save_kind="autosave",
                    ),
                )
                outcomes.append(text_value)
            except RevisionConflict:
                outcomes.append("conflict")
        finally:
            session.close()

    threads = [
        threading.Thread(target=save, args=("甲侧正文",)),
        threading.Thread(target=save, args=("乙侧正文",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert sorted(outcomes) == ["conflict", "甲侧正文"] or sorted(outcomes) == [
        "conflict",
        "乙侧正文",
    ]
    stored = _body(auth_client, chapter["id"])
    assert stored in {"甲侧正文", "乙侧正文"}
    assert _revision(auth_client, chapter["id"]) == int(chapter["revision"]) + 1
    after_save = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    assert [item["change_source"] for item in after_save] == ["manual"]

    novel, chapter = _seed(auth_client, "并发采纳")
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_tokens=["只写一次"]),
    )
    task = _wait(auth_client, created.json()["id"])
    barrier = threading.Barrier(2)
    results: list[str] = []

    def accept() -> None:
        session = factory()
        try:
            barrier.wait(5)
            try:
                accept_ai_task(
                    session,
                    task["id"],
                    AiTaskAccept(target_revision=int(chapter["revision"]), apply_mode="append"),
                )
                results.append("accepted")
            except (RevisionConflict, TaskStateError):
                results.append("rejected")
        finally:
            session.close()

    threads = [threading.Thread(target=accept), threading.Thread(target=accept)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert sorted(results) == ["accepted", "rejected"]
    assert _body(auth_client, chapter["id"]) == "原有正文\n\n只写一次"
    assert auth_client.get(f"/api/v1/ai/tasks/{task['id']}").json()["resolution"] == "accepted"


def test_closed_stream_still_returns_the_candidate(auth_client: TestClient) -> None:
    novel, chapter = _seed(auth_client, "断线")
    created = auth_client.post(
        "/api/v1/ai/tasks",
        json=_task(novel, chapter, mock_tokens=["甲", "乙", "丙"]),
    )
    task_id = created.json()["id"]
    with auth_client.stream("GET", f"/api/v1/ai/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        response.close()
    task = _wait(auth_client, task_id)
    assert task["status"] == "completed"
    assert task["output_text"] == "甲乙丙"
    assert _body(auth_client, chapter["id"]) == "原有正文"

    from app.ai.mock_provider import MockScript, pop_mock_script, register_mock_script

    script = MockScript(hold_before=1)
    register_mock_script("late-after-cancel", script)
    try:
        running = auth_client.post(
            "/api/v1/ai/tasks",
            json=_task(
                novel,
                chapter,
                mock_tokens=["甲", "乙"],
                mock_script_id="late-after-cancel",
            ),
        )
        running_id = running.json()["id"]
        assert script.reached.wait(5)
        cancelled = auth_client.post(f"/api/v1/ai/tasks/{running_id}/cancel")
        assert cancelled.status_code == 200
        script.release.set()
        assert script.processed.wait(5)
        assert (
            _write_output(auth_client.app.state.session_factory, running_id, "甲乙污染", 3) is False
        )
        final = auth_client.get(f"/api/v1/ai/tasks/{running_id}").json()
        assert final["status"] == "cancelled"
        assert final["output_text"] == "甲"
        assert "污染" not in (final["output_text"] or "")
        assert _body(auth_client, chapter["id"]) == "原有正文"
    finally:
        script.release.set()
        pop_mock_script("late-after-cancel")


def test_restore_preview_keeps_intermediate_versions(auth_client: TestClient) -> None:
    _novel, chapter = _seed(auth_client, "版本")
    first = _put(auth_client, chapter["id"], int(chapter["revision"]), "第一稿", "manual")
    second = _put(auth_client, chapter["id"], int(first["revision"]), "第二稿", "manual")
    third = _put(auth_client, chapter["id"], int(second["revision"]), "第三稿", "manual")
    listed = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    by_text = {item["preview"]: item for item in listed}
    assert [item["change_source"] for item in listed] == ["manual", "manual", "manual", "manual"]

    detail = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions/{by_text['第一稿']['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["text"] == "第一稿"
    assert detail.json()["change_source"] == "manual"
    assert detail.json()["memory_proposal_ids"] == []
    assert _revision(auth_client, chapter["id"]) == third["revision"]

    compared = auth_client.get(
        f"/api/v1/chapters/{chapter['id']}/versions/diff",
        params={"left_id": by_text["第一稿"]["id"], "right_id": by_text["第三稿"]["id"]},
    )
    assert compared.status_code == 200, compared.text
    ops = [item["op"] for item in compared.json()["hunks"]]
    assert "delete" in ops
    assert "insert" in ops
    assert compared.json()["left"]["revision"] == by_text["第一稿"]["revision"]
    assert compared.json()["right"]["revision"] == by_text["第三稿"]["revision"]
    joined = "\n".join(item["text"] for item in compared.json()["hunks"])
    assert "第一稿" in joined
    assert "第三稿" in joined

    against_current = auth_client.get(
        f"/api/v1/chapters/{chapter['id']}/versions/diff",
        params={"left_id": by_text["第二稿"]["id"], "right_id": "current"},
    )
    assert against_current.status_code == 200, against_current.text
    assert against_current.json()["right"]["label"] == "当前正文"
    assert against_current.json()["right"]["revision"] == third["revision"]
    assert _revision(auth_client, chapter["id"]) == third["revision"]

    restored = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/restore",
        json={"revision": third["revision"], "version_id": by_text["第一稿"]["id"]},
    )
    assert restored.status_code == 200, restored.text
    assert document_to_text(restored.json()["content"]) == "第一稿"
    assert restored.json()["revision"] == third["revision"] + 1
    after = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    revisions = sorted(item["revision"] for item in after)
    assert second["revision"] in revisions
    assert third["revision"] in revisions
    assert restored.json()["revision"] in revisions
    assert len(after) == len(listed) + 1
    restored_row = next(item for item in after if item["revision"] == restored.json()["revision"])
    assert restored_row["change_source"] == "restore"
    assert restored_row["ai_task_id"] is None


def test_version_links_memory_analysis(auth_client: TestClient) -> None:
    _novel, chapter = _seed(auth_client, "记忆来源")
    saved = _put(auth_client, chapter["id"], int(chapter["revision"]), "林晚说道天黑了。", "manual")
    analyzed = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/analyze",
        json={"revision": saved["revision"], "use_mock": True},
    )
    assert analyzed.status_code == 200, analyzed.text
    proposal_ids = [item["id"] for item in analyzed.json()["proposals"]]
    assert proposal_ids
    versions = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions").json()
    detail = auth_client.get(f"/api/v1/chapters/{chapter['id']}/versions/{versions[0]['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["revision"] == saved["revision"]
    assert set(detail.json()["memory_proposal_ids"]) == set(proposal_ids)


def test_provider_errors_hide_secrets_and_bodies() -> None:
    import httpx

    from app.ai.openai_provider import OpenAICompatibleProvider
    from app.ai.provider import GenerationRequest, ModelEndpoint
    from app.core.logging import JsonFormatter
    from app.core.redaction import redact_text

    def endpoint() -> ModelEndpoint:
        return ModelEndpoint(
            base_url="https://example.invalid/v1",
            model_name="demo",
            api_key=SECRET,
            timeout_seconds=1,
            supports_streaming=False,
            max_retries=0,
        )

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException(f"timed out Authorization: Bearer {SECRET}")

    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(timeout), sleeper=lambda _s: None
    )
    with pytest.raises(Exception) as timeout_error:
        provider.generate(GenerationRequest(endpoint=endpoint(), prompt="ping"))
    assert getattr(timeout_error.value, "code", "") == "MODEL_TIMEOUT"
    assert SECRET not in str(timeout_error.value)

    def limited(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": SECRET}})

    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(limited), sleeper=lambda _s: None
    )
    with pytest.raises(Exception) as limit_error:
        provider.generate(GenerationRequest(endpoint=endpoint(), prompt="ping"))
    assert getattr(limit_error.value, "code", "") == "MODEL_RATE_LIMIT"
    assert SECRET not in str(limit_error.value)
    assert "限流" in str(limit_error.value)

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"not-json {SECRET}")

    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(broken), sleeper=lambda _s: None
    )
    with pytest.raises(Exception) as format_error:
        provider.generate(GenerationRequest(endpoint=endpoint(), prompt="ping"))
    assert getattr(format_error.value, "code", "") == "MODEL_BAD_RESPONSE"
    assert SECRET not in str(format_error.value)
    assert "not-json" not in str(format_error.value)

    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signaturevalue"
    raw = f"access_token={token} Authorization: Bearer {token} api_key={SECRET}"
    redacted = redact_text(raw)
    assert token not in redacted
    assert SECRET not in redacted
    record_text = JsonFormatter().format(_log(raw))
    assert token not in record_text
    assert SECRET not in record_text


def _log(message: str):
    import logging

    return logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _seed(client: TestClient, title: str) -> tuple[dict[str, object], dict[str, object]]:
    novel = client.post("/api/v1/novels", json={"title": title}).json()
    created = client.post(f"/api/v1/novels/{novel['id']}/chapters", json={"title": "第一章"}).json()
    saved = _put(client, created["id"], int(created["revision"]), "原有正文", "manual")
    return novel, saved


def _task(
    novel: dict[str, object], chapter: dict[str, object], **extra: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "novel_id": novel["id"],
        "chapter_id": chapter["id"],
        "task_type": "continue",
        "instruction": "往后写一句",
        "target_revision": chapter["revision"],
        "use_mock": True,
        "mock_tokens": ["候", "选"],
    }
    body.update(extra)
    return body


def _wait(client: TestClient, task_id: object) -> dict[str, object]:
    import time

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


def _put(
    client: TestClient,
    chapter_id: object,
    revision: int,
    text_value: str,
    kind: str,
) -> dict[str, object]:
    response = client.put(
        f"/api/v1/chapters/{chapter_id}",
        json={"revision": revision, "save_kind": kind, "content": text_to_document(text_value)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _put_new(
    client: TestClient, novel_id: object, title: str, text_value: str
) -> dict[str, object]:
    created = client.post(f"/api/v1/novels/{novel_id}/chapters", json={"title": title})
    assert created.status_code == 201, created.text
    chapter = created.json()
    return _put(client, chapter["id"], int(chapter["revision"]), text_value, "manual")


def _body(client: TestClient, chapter_id: object) -> str:
    response = client.get(f"/api/v1/chapters/{chapter_id}")
    assert response.status_code == 200, response.text
    return document_to_text(response.json()["content"])


def _revision(client: TestClient, chapter_id: object) -> int:
    response = client.get(f"/api/v1/chapters/{chapter_id}")
    assert response.status_code == 200
    revision = response.json()["revision"]
    assert isinstance(revision, int)
    return revision


def _repair_for(client: TestClient, novel_id: object, chapter_id: object) -> dict[str, object]:
    checked = client.post(f"/api/v1/novels/{novel_id}/quality-check", json={"use_model": False})
    assert checked.status_code == 200, checked.text
    issues = [
        item
        for item in checked.json()["issues"]
        if item["chapter_id"] == chapter_id and item["status"] == "pending"
    ]
    assert issues, checked.text
    suggested = client.post(f"/api/v1/quality-issues/{issues[0]['id']}/repairs", json={})
    assert suggested.status_code == 200, suggested.text
    candidate = next(item for item in suggested.json()["candidates"] if item["applicable"])
    assert isinstance(candidate, dict)
    candidate["issue_id"] = issues[0]["id"]
    return candidate


def _insert_event(*, novel_id: object, chapter_id: object, description: str, quote: str) -> None:
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
