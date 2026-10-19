"""Empty database can be upgraded with Alembic."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_empty_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "migrate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        indexes = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            ).scalars()
        )
        chapter_fks = {
            row[2] for row in connection.execute(text("PRAGMA foreign_key_list(chapters)")).all()
        }
    engine.dispose()

    assert version == "0010_version_provenance"
    assert {
        "alembic_version",
        "novels",
        "volumes",
        "chapters",
        "chapter_versions",
        "model_configs",
        "ai_tasks",
        "story_entities",
        "entity_states",
        "story_events",
        "chapter_summaries",
        "memory_change_proposals",
        "foreshadowing",
        "writing_goals",
        "story_plans",
        "chapter_outlines",
        "scene_cards",
        "entity_relations",
        "quality_issues",
        "quality_repair_candidates",
    } <= tables
    assert "ix_chapters_novel_id_sort_order" in indexes
    assert "ix_chapters_volume_id_sort_order" in indexes
    assert "ix_volumes_novel_id_sort_order" in indexes
    assert "ix_ai_tasks_novel_id" in indexes
    assert "ix_ai_tasks_status" in indexes
    assert "ix_model_configs_is_enabled" in indexes
    assert "ix_story_entities_novel_id" in indexes
    assert "ix_memory_change_proposals_novel_id_status" in indexes
    assert "ix_chapter_summaries_chapter_id" in indexes
    assert "ix_story_events_novel_id" in indexes
    assert "ix_entity_states_entity_id" in indexes
    assert "ix_foreshadowing_novel_id" in indexes
    assert "ix_foreshadowing_novel_id_status" in indexes
    assert "ix_chapter_outlines_novel_id" in indexes
    assert "ix_scene_cards_novel_id" in indexes
    assert "ix_scene_cards_chapter_id_sort_order" in indexes
    assert "ix_entity_relations_novel_id" in indexes
    assert "ix_entity_relations_from_entity_id" in indexes
    assert "ix_entity_relations_to_entity_id" in indexes
    assert "ix_quality_issues_novel_id" in indexes
    assert "ix_quality_issues_novel_id_status" in indexes
    assert "ix_quality_repair_candidates_issue_id" in indexes
    assert "novels" in chapter_fks
    assert "volumes" in chapter_fks


def test_upgrade_from_previous_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "from-baseline.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    command.upgrade(config, "0001_initial")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
    assert version == "0001_initial"
    assert "novels" not in tables

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
    engine.dispose()
    assert version == "0010_version_provenance"
    assert "chapters" in tables
    assert "chapter_versions" in tables
    assert "model_configs" in tables
    assert "ai_tasks" in tables
    assert "story_plans" in tables
    assert "chapter_outlines" in tables
    assert "scene_cards" in tables
    assert "entity_relations" in tables


def test_upgrade_from_catalog_keeps_chapters_and_adds_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-catalog.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0002_catalog")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '升级前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapters (
                    id, novel_id, volume_id, title, sort_order, content,
                    content_format, content_format_version, word_count, status,
                    revision, created_at, updated_at, deleted_at
                ) VALUES (
                    'chapter-1', 'novel-1', NULL, '旧章', 0,
                    '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"升级前正文"}]}]}',
                    'tiptap_json', 1, 5, 'draft', 1,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        stored = connection.execute(
            text("SELECT content FROM chapters WHERE id = 'chapter-1'")
        ).scalar_one()
        version_count = connection.execute(
            text("SELECT COUNT(*) FROM chapter_versions")
        ).scalar_one()
        index_rows = connection.execute(text("PRAGMA index_list('chapter_versions')")).all()
        foreign_keys = connection.execute(text("PRAGMA foreign_key_list(chapter_versions)")).all()
        table_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'chapter_versions'")
        ).scalar_one()
        assert version == "0010_version_provenance"
        assert "升级前正文" in str(stored)
        assert version_count == 0
        unique_name = next(row[1] for row in index_rows if row[2] == 1 and row[3] == "u")
        unique_columns = [
            row[2] for row in connection.execute(text(f"PRAGMA index_info('{unique_name}')")).all()
        ]
        assert unique_columns == ["chapter_id", "revision"]
        assert "uq_chapter_versions_chapter_id_revision" in table_sql
        assert any(row[2] == "chapters" and row[3] == "chapter_id" for row in foreign_keys)
        assert "ck_chapter_versions_change_source" in table_sql
        assert "ai_accepted" in table_sql

    command.downgrade(config, "0002_catalog")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        stored = connection.execute(
            text("SELECT title FROM chapters WHERE id = 'chapter-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0002_catalog"
    assert "chapter_versions" not in tables
    assert "ai_tasks" not in tables
    assert "model_configs" not in tables
    assert stored == "旧章"


def test_upgrade_from_chapter_versions_adds_ai_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-versions.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0003_chapter_versions")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '版本后', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        title = connection.execute(
            text("SELECT title FROM novels WHERE id = 'novel-1'")
        ).scalar_one()
        ai_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ai_tasks'")
        ).scalar_one()
        config_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'model_configs'")
        ).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_key_list(ai_tasks)")).all()
    engine.dispose()

    assert version == "0010_version_provenance"
    assert title == "版本后"
    assert "ck_ai_tasks_status" in ai_sql
    assert "ck_ai_tasks_resolution" in ai_sql
    assert "secret_ref" in config_sql
    assert any(row[2] == "novels" and row[3] == "novel_id" for row in foreign_keys)
    assert any(row[2] == "model_configs" and row[3] == "model_config_id" for row in foreign_keys)


def test_upgrade_from_ai_tables_adds_memory_and_keeps_novels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-ai.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0004_ai")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '记忆前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        title = connection.execute(
            text("SELECT title FROM novels WHERE id = 'novel-1'")
        ).scalar_one()
        proposal_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'memory_change_proposals'")
        ).scalar_one()
        foreshadow_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'foreshadowing'")
        ).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_key_list(entity_states)")).all()
    assert version == "0010_version_provenance"
    assert title == "记忆前"
    assert "ck_foreshadowing_status" in foreshadow_sql
    assert "abandoned" in foreshadow_sql
    assert "ck_memory_change_proposals_status" in proposal_sql
    assert "stale" in proposal_sql
    assert "ck_memory_change_proposals_certainty" in proposal_sql
    assert any(row[2] == "story_entities" and row[3] == "entity_id" for row in foreign_keys)
    assert any(row[2] == "chapters" and row[3] == "chapter_id" for row in foreign_keys)

    command.downgrade(config, "0004_ai")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        title = connection.execute(
            text("SELECT title FROM novels WHERE id = 'novel-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0004_ai"
    assert title == "记忆前"
    assert "story_entities" not in tables
    assert "memory_change_proposals" not in tables
    assert "foreshadowing" not in tables
    assert "writing_goals" not in tables
    assert "story_plans" not in tables
    assert "chapter_outlines" not in tables
    assert "scene_cards" not in tables
    assert "ai_tasks" in tables


def test_upgrade_from_quality_adds_planning_and_keeps_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-quality.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0006_quality")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '规划前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapters (
                    id, novel_id, volume_id, title, sort_order, content,
                    content_format, content_format_version, word_count, status,
                    revision, created_at, updated_at, deleted_at
                ) VALUES (
                    'chapter-1', 'novel-1', NULL, '旧章', 0,
                    '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"升级前正文"}]}]}',
                    'tiptap_json', 1, 5, 'draft', 3,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        stored = connection.execute(
            text("SELECT content, revision FROM chapters WHERE id = 'chapter-1'")
        ).one()
        plan_count = connection.execute(text("SELECT COUNT(*) FROM story_plans")).scalar_one()
        outline_count = connection.execute(
            text("SELECT COUNT(*) FROM chapter_outlines")
        ).scalar_one()
        scene_count = connection.execute(text("SELECT COUNT(*) FROM scene_cards")).scalar_one()
        outline_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'chapter_outlines'")
        ).scalar_one()
        scene_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'scene_cards'")
        ).scalar_one()
    assert version == "0010_version_provenance"
    assert stored[1] == 3
    assert "升级前正文" in str(stored[0])
    assert plan_count == 0
    assert outline_count == 0
    assert scene_count == 0
    assert "uq_chapter_outlines_chapter_id" in outline_sql
    assert "ck_chapter_outlines_status" in outline_sql
    assert "ck_scene_cards_status" in scene_sql
    assert "draft" in outline_sql and "confirmed" in outline_sql

    command.downgrade(config, "0006_quality")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        stored_title = connection.execute(
            text("SELECT title FROM chapters WHERE id = 'chapter-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0006_quality"
    assert stored_title == "旧章"
    assert "story_plans" not in tables
    assert "chapter_outlines" not in tables
    assert "scene_cards" not in tables
    assert "chapters" in tables
    assert "foreshadowing" in tables


def test_upgrade_from_planning_adds_bible_and_keeps_entities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-planning.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0007_story_planning")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '圣经前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapters (
                    id, novel_id, volume_id, title, sort_order, content,
                    content_format, content_format_version, word_count, status,
                    revision, created_at, updated_at, deleted_at
                ) VALUES (
                    'chapter-1', 'novel-1', NULL, '旧章', 0,
                    '{"type":"doc","content":[]}',
                    'tiptap_json', 1, 2, 'draft', 4,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO story_entities (
                    id, novel_id, entity_type, name, aliases, profile, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'entity-1', 'novel-1', 'character', '林晚', '[]',
                    '{"summary":"升级前档案"}', 'active',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO entity_states (
                    id, entity_id, chapter_id, source_revision, proposal_id,
                    state_data, evidence_quote, source_type, created_at
                ) VALUES (
                    'state-1', 'entity-1', 'chapter-1', 4, NULL,
                    '{"summary":"旧伤"}', '左臂旧伤', 'manual',
                    '2026-01-01 00:00:00'
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        name = connection.execute(
            text("SELECT name FROM story_entities WHERE id = 'entity-1'")
        ).scalar_one()
        validity = connection.execute(
            text("SELECT valid_from_text, valid_until_text FROM entity_states WHERE id = 'state-1'")
        ).one()
        relation_count = connection.execute(
            text("SELECT COUNT(*) FROM entity_relations")
        ).scalar_one()
        relation_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'entity_relations'")
        ).scalar_one()
        revision = connection.execute(
            text("SELECT revision FROM chapters WHERE id = 'chapter-1'")
        ).scalar_one()
    assert version == "0010_version_provenance"
    assert name == "林晚"
    assert validity == (None, None)
    assert relation_count == 0
    assert revision == 4
    assert "ck_entity_relations_distinct_ends" in relation_sql
    assert "ck_entity_relations_status" in relation_sql

    command.downgrade(config, "0007_story_planning")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(entity_states)")).all()
        }
        kept = connection.execute(
            text("SELECT profile FROM story_entities WHERE id = 'entity-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0007_story_planning"
    assert "entity_relations" not in tables
    assert "valid_from_text" not in columns
    assert "valid_until_text" not in columns
    assert "升级前档案" in str(kept)
    assert "story_entities" in tables


def test_upgrade_from_story_bible_adds_quality_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-bible.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0008_story_bible")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '质量前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapters (
                    id, novel_id, volume_id, title, sort_order, content,
                    content_format, content_format_version, word_count, status,
                    revision, created_at, updated_at, deleted_at
                ) VALUES (
                    'chapter-1', 'novel-1', NULL, '旧章', 0,
                    '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"升级前正文"}]}]}',
                    'tiptap_json', 1, 4, 'draft', 3,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        issue_count = connection.execute(text("SELECT COUNT(*) FROM quality_issues")).scalar_one()
        repair_count = connection.execute(
            text("SELECT COUNT(*) FROM quality_repair_candidates")
        ).scalar_one()
        issue_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'quality_issues'")
        ).scalar_one()
        stored = connection.execute(
            text("SELECT revision, content FROM chapters WHERE id = 'chapter-1'")
        ).one()
    assert version == "0010_version_provenance"
    assert issue_count == 0
    assert repair_count == 0
    assert stored[0] == 3
    assert "升级前正文" in str(stored[1])
    assert "ck_quality_issues_status" in issue_sql
    assert "pending" in issue_sql and "expired" in issue_sql
    assert "uq_quality_issues_novel_fingerprint" in issue_sql

    command.downgrade(config, "0008_story_bible")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        kept = connection.execute(
            text("SELECT title FROM chapters WHERE id = 'chapter-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0008_story_bible"
    assert "quality_issues" not in tables
    assert "quality_repair_candidates" not in tables
    assert kept == "旧章"
    assert "chapters" in tables
    assert "entity_relations" in tables


def test_upgrade_from_quality_issues_adds_version_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "from-quality.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "0009_quality_issues")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO novels (
                    id, title, genre, synopsis, style_guide, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    'novel-1', '可靠性前', NULL, NULL, NULL, 'draft',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapters (
                    id, novel_id, volume_id, title, sort_order, content,
                    content_format, content_format_version, word_count, status,
                    revision, created_at, updated_at, deleted_at
                ) VALUES (
                    'chapter-1', 'novel-1', NULL, '旧章', 0,
                    '{"type":"doc","content":[]}',
                    'tiptap_json', 1, 2, 'draft', 4,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chapter_versions (
                    id, chapter_id, revision, content_snapshot, content_format,
                    content_format_version, change_source, change_note, created_at
                ) VALUES (
                    'version-1', 'chapter-1', 4, '{"type":"doc","content":[]}',
                    'tiptap_json', 1, 'manual', NULL, '2026-01-02 00:00:00'
                )
                """
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        row = connection.execute(
            text(
                """
                SELECT revision, change_source, ai_task_id, repair_candidate_id
                FROM chapter_versions WHERE id = 'version-1'
                """
            )
        ).one()
        links = connection.execute(text("PRAGMA foreign_key_list(chapter_versions)")).all()
    assert version == "0010_version_provenance"
    assert row == (4, "manual", None, None)
    assert any(item[2] == "ai_tasks" and item[3] == "ai_task_id" for item in links)
    assert any(
        item[2] == "quality_repair_candidates" and item[3] == "repair_candidate_id"
        for item in links
    )

    command.downgrade(config, "0009_quality_issues")
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        columns = {
            item[1]
            for item in connection.execute(text("PRAGMA table_info(chapter_versions)")).all()
        }
        kept = connection.execute(
            text("SELECT change_source FROM chapter_versions WHERE id = 'version-1'")
        ).scalar_one()
    engine.dispose()
    assert version == "0009_quality_issues"
    assert "ai_task_id" not in columns
    assert "repair_candidate_id" not in columns
    assert kept == "manual"
