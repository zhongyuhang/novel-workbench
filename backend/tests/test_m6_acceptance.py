"""M6 acceptance: T-017 backup/restore and T-018 authenticated LAN access."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.passwords import hash_password
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SECRET = "sk-backup-test-key-should-not-leak"


def _paragraph(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _production_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'prod.db'}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_AUTH_SECRET", "p" * 40)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "local-access-password")
    monkeypatch.setenv("APP_ACCESS_PASSWORD_HASH", "")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:8080")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1")
    monkeypatch.setenv("FRONTEND_DIST", "")
    get_settings.cache_clear()


def test_t018_unauthenticated_routes_reject_until_login(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    novels = client.get("/api/v1/novels")
    created = client.post("/api/v1/admin/backups")
    listed = client.get("/api/v1/admin/backups")

    assert health.status_code == 200
    assert novels.status_code == 401
    assert novels.json()["error"]["code"] == "UNAUTHENTICATED"
    assert created.status_code == 401
    assert listed.status_code == 401

    session = client.post("/api/v1/auth/session", json={"password": ""})
    assert session.status_code == 200, session.text
    token = session.json()["access_token"]
    authed = client.get("/api/v1/novels", headers={"Authorization": f"Bearer {token}"})
    assert authed.status_code == 200
    assert authed.json() == []


def test_t018_configured_password_rejects_then_accepts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("APP_ACCESS_PASSWORD_HASH", "")
    get_settings.cache_clear()

    missing = client.get("/api/v1/novels")
    empty = client.post("/api/v1/auth/session", json={"password": ""})
    wrong = client.post("/api/v1/auth/session", json={"password": "wrong-passphrase"})
    allowed = client.post("/api/v1/auth/session", json={"password": "correct-horse-battery"})

    assert missing.status_code == 401
    assert empty.status_code == 401
    assert empty.json()["error"]["code"] == "PASSWORD_REQUIRED"
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "INVALID_PASSWORD"
    assert allowed.status_code == 200, allowed.text

    token = allowed.json()["access_token"]
    novels = client.get("/api/v1/novels", headers={"Authorization": f"Bearer {token}"})
    assert novels.status_code == 200


def test_password_hash_is_what_login_checks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = hash_password("correct-horse-battery", iterations=10_000)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "plaintext-should-not-login")
    monkeypatch.setenv("APP_ACCESS_PASSWORD_HASH", stored)
    get_settings.cache_clear()

    plaintext = client.post(
        "/api/v1/auth/session",
        json={"password": "plaintext-should-not-login"},
    )
    hashed = client.post("/api/v1/auth/session", json={"password": "correct-horse-battery"})

    assert plaintext.status_code == 401
    assert hashed.status_code == 200, hashed.text
    token = hashed.json()["access_token"]
    novels = client.get("/api/v1/novels", headers={"Authorization": f"Bearer {token}"})
    assert novels.status_code == 200


def test_production_rejects_empty_and_weak_passwords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _production_base(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="APP_ACCESS_PASSWORD"):
        create_app()

    monkeypatch.setenv("APP_ACCESS_PASSWORD", "short-pass")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="APP_ACCESS_PASSWORD"):
        create_app()

    monkeypatch.setenv("APP_ACCESS_PASSWORD", "123456789012")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="APP_ACCESS_PASSWORD"):
        create_app()


def test_production_rejects_short_auth_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _production_base(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_AUTH_SECRET", "short-secret")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="APP_AUTH_SECRET"):
        create_app()


def test_production_rejects_low_iteration_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _production_base(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "")
    monkeypatch.setenv(
        "APP_ACCESS_PASSWORD_HASH",
        hash_password("correct-horse-battery", iterations=10_000),
    )
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="iterations"):
        create_app()


def test_lan_bind_requires_a_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_AUTH_SECRET", "l" * 40)
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "")
    monkeypatch.setenv("APP_ACCESS_PASSWORD_HASH", "")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lan.db'}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="APP_ACCESS_PASSWORD"):
        create_app()


def test_production_rejects_unlisted_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _production_base(monkeypatch, tmp_path)
    application = create_app()
    with TestClient(application) as prod_client:
        allowed = prod_client.get("/api/v1/health", headers={"Host": "localhost"})
        blocked = prod_client.get("/api/v1/health", headers={"Host": "evil.example"})

    assert allowed.status_code == 200
    assert blocked.status_code == 400


def test_frontend_dist_does_not_shadow_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "frontend"
    dist.mkdir()
    (dist / "index.html").write_text("<title>novel-workbench</title>", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    get_settings.cache_clear()

    application = create_app()
    with TestClient(application) as test_client:
        page = test_client.get("/")
        health = test_client.get("/api/v1/health")
        docs = test_client.get("/docs")

    assert page.status_code == 200
    assert "novel-workbench" in page.text
    assert health.status_code == 200
    assert health.json()["version"] == "1.0.0"
    assert docs.status_code == 200


def test_t017_backup_then_restore_into_a_new_database(
    auth_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = auth_client.post(
        "/api/v1/novels",
        json={"title": "备份作品", "synopsis": "恢复后仍在"},
    ).json()
    chapter = auth_client.post(
        f"/api/v1/novels/{novel['id']}/chapters",
        json={"title": "第一章"},
    ).json()
    saved = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}",
        json={
            "revision": chapter["revision"],
            "content": _paragraph("备份里的句子。。"),
            "content_format": "tiptap_json",
            "save_kind": "manual",
        },
    )
    assert saved.status_code == 200, saved.text
    entity = auth_client.post(
        f"/api/v1/novels/{novel['id']}/entities",
        json={
            "entity_type": "character",
            "name": "林晚",
            "profile": {"summary": "左臂旧伤"},
        },
    )
    assert entity.status_code == 201, entity.text
    model = auth_client.post(
        "/api/v1/settings/models",
        json={
            "display_name": "备份里的模型",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model_name": "demo-model",
            "api_key": SECRET,
        },
    )
    assert model.status_code == 201, model.text
    plan = auth_client.put(
        f"/api/v1/novels/{novel['id']}/story-plan",
        json={"logline": "备份里的大纲", "body": "全书结构"},
    )
    assert plan.status_code == 200, plan.text
    outline = auth_client.put(
        f"/api/v1/chapters/{chapter['id']}/outline",
        json={"goal": "备份里的章节目标"},
    )
    assert outline.status_code == 200, outline.text
    scene = auth_client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"goal": "备份里的场景", "turning_point": "转折还在"},
    )
    assert scene.status_code == 201, scene.text
    checked = auth_client.post(f"/api/v1/novels/{novel['id']}/quality-check", json={})
    assert checked.status_code == 200, checked.text
    assert checked.json()["manuscript_changed"] is False
    issue = next(
        item for item in checked.json()["issues"] if item["rule_id"] == "text.repeated_punctuation"
    )
    assert issue["evidence_status"] == "sufficient"

    created = auth_client.post("/api/v1/admin/backups")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["app_version"] == "1.0.0"
    assert body["alembic_revision"] == "0009_quality_issues"
    assert "database" not in body
    assert str(tmp_path) not in created.text
    assert SECRET not in created.text

    listed = auth_client.get("/api/v1/admin/backups")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == body["id"]
    assert SECRET not in listed.text

    backup_dir = Path(get_settings().resolved_data_dir) / "backups" / body["id"]
    assert (backup_dir / "manifest.json").is_file()
    assert (backup_dir / "database.sqlite").is_file()
    assert backup_dir.is_relative_to(get_settings().resolved_data_dir)
    with sqlite3.connect(backup_dir / "database.sqlite") as backed_up:
        tables = {
            row[0]
            for row in backed_up.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        stored_plan = backed_up.execute("SELECT logline FROM story_plans").fetchone()
        stored_scene = backed_up.execute("SELECT goal FROM scene_cards").fetchone()
        stored_issue = backed_up.execute(
            "SELECT rule_id, manuscript_snippet FROM quality_issues"
        ).fetchone()
    assert {"story_plans", "chapter_outlines", "scene_cards", "quality_issues"} <= tables
    assert "quality_repair_candidates" in tables
    assert stored_plan == ("备份里的大纲",)
    assert stored_scene == ("备份里的场景",)
    assert stored_issue is not None
    assert stored_issue[0] == "text.repeated_punctuation"

    fresh_db = tmp_path / "restored-env" / "ai_novel_writer.db"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli.restore",
            "--backup",
            str(backup_dir),
            "--database",
            str(fresh_db),
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
    )
    assert completed.returncode == 0, completed.stderr
    assert body["id"] in completed.stdout

    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli.restore",
            "--backup",
            str(backup_dir),
            "--database",
            str(fresh_db),
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
    )
    assert refused.returncode == 2
    assert "force" in refused.stderr

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{fresh_db}")
    monkeypatch.setenv("DATA_DIR", str(fresh_db.parent))
    get_settings.cache_clear()
    restored_app = create_app()
    with TestClient(restored_app) as restored:
        token = restored.post("/api/v1/auth/session", json={"password": ""}).json()["access_token"]
        restored.headers.update({"Authorization": f"Bearer {token}"})
        novels = restored.get("/api/v1/novels")
        assert novels.status_code == 200, novels.text
        assert novels.json()[0]["title"] == "备份作品"
        assert novels.json()[0]["synopsis"] == "恢复后仍在"
        novel_id = novels.json()[0]["id"]
        chapters = restored.get(f"/api/v1/novels/{novel_id}/chapters")
        assert chapters.status_code == 200, chapters.text
        chapter_id = chapters.json()[0]["id"]
        current = restored.get(f"/api/v1/chapters/{chapter_id}")
        assert current.json()["content"]["content"][0]["content"][0]["text"] == "备份里的句子。。"
        versions = restored.get(f"/api/v1/chapters/{chapter_id}/versions")
        assert versions.status_code == 200, versions.text
        assert versions.json()[0]["preview"] == "备份里的句子。。"
        restored_issues = restored.get(f"/api/v1/novels/{novel_id}/quality-issues")
        assert restored_issues.status_code == 200, restored_issues.text
        assert any(
            item["rule_id"] == "text.repeated_punctuation" for item in restored_issues.json()
        )
        entities = restored.get(f"/api/v1/novels/{novel_id}/entities")
        assert entities.status_code == 200, entities.text
        assert entities.json()[0]["name"] == "林晚"
        assert entities.json()[0]["profile"]["summary"] == "左臂旧伤"
        models = restored.get("/api/v1/settings/models")
        assert models.status_code == 200, models.text
        assert models.json()[0]["display_name"] == "备份里的模型"
        assert SECRET not in models.text
        restored_plan = restored.get(f"/api/v1/novels/{novel_id}/story-plan")
        assert restored_plan.status_code == 200, restored_plan.text
        assert restored_plan.json()["plan"]["logline"] == "备份里的大纲"
        assert restored_plan.json()["plan"]["counts_as_fact"] is False
        restored_outline = restored.get(f"/api/v1/chapters/{chapter_id}/outline")
        assert restored_outline.json()["outline"]["goal"] == "备份里的章节目标"
        restored_scenes = restored.get(f"/api/v1/chapters/{chapter_id}/scenes")
        assert restored_scenes.json()[0]["goal"] == "备份里的场景"
        assert restored_scenes.json()[0]["turning_point"] == "转折还在"
        assert restored_scenes.json()[0]["sort_order"] == 0


def test_compose_file_persists_data_and_does_not_enable_reload() -> None:
    compose = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    caddy = (REPO_ROOT / "deploy" / "Caddyfile.example").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "DATA_DIR" in compose
    assert "/data" in compose
    assert "APP_ENV" in compose
    assert "healthcheck" in compose
    assert "--reload" not in compose
    assert "--reload" not in entrypoint
    assert "uvicorn" in entrypoint
    assert "alembic upgrade head" in entrypoint
    assert "reverse_proxy" in caddy
    assert "npm run build" in dockerfile
    assert "--reload" not in dockerfile
