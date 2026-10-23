"""Versioned novel packages.

Markdown/TXT export stays a reading copy. This archive is the portable work:
JSON metadata plus one Markdown and one TXT file per live chapter, in catalog
order. Import always creates a new novel. Conflicting ids are remapped.
A failed import rolls back and leaves no partial rows.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import re
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app import __version__
from app.core.content import (
    CANONICAL_CONTENT_FORMAT,
    CANONICAL_CONTENT_FORMAT_VERSION,
    validate_document,
    word_count,
)
from app.core.errors import (
    InvalidDocument,
    NotFound,
    PackageImportFailed,
    PackageInvalid,
    UnsupportedPackage,
)
from app.core.manuscript import document_to_markdown, document_to_plain
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume
from app.models.memory import (
    ChapterSummary,
    EntityRelation,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard, StoryArc, StoryPlan, VolumeOutline
from app.models.quality import Foreshadowing, QualityIssue, QualityRepairCandidate, WritingGoal
from app.repositories import catalog as catalog_repo

logger = logging.getLogger("app.portable")

FORMAT = "ai-novel-writer-portable-v1"
FORMAT_VERSION = 1
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 160 * 1024 * 1024
MAX_MEMBERS = 4000
MAX_ROWS = 5000
MAX_TEXT = 1_500_000
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
# Names that end with _id but are not row references.
_LABEL_ID_KEYS = frozenset({"rule_id"})
_FILENAME_UNSAFE = re.compile(r"[\\/:*?\"<>|\r\n]+")
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "secret_ref",
    "password",
    "access_token",
    "refresh_token",
    "authorization",
    "app_access_password",
    "app_access_password_hash",
    "app_auth_secret",
    "app_secret_encryption_key",
}
_KINDS = (
    "novels",
    "volumes",
    "chapters",
    "chapter_versions",
    "story_plans",
    "story_arcs",
    "volume_outlines",
    "chapter_outlines",
    "scene_cards",
    "entities",
    "entity_states",
    "relations",
    "events",
    "summaries",
    "proposals",
    "foreshadowing",
    "writing_goals",
    "quality_issues",
    "repair_candidates",
    "ai_tasks",
    "model_configs",
)
_LABELS = {
    "novels": "作品",
    "volumes": "卷",
    "chapters": "章节",
    "chapter_versions": "章节版本",
    "story_plans": "作品大纲",
    "story_arcs": "故事线",
    "volume_outlines": "卷大纲",
    "chapter_outlines": "章节大纲",
    "scene_cards": "场景卡片",
    "entities": "设定",
    "entity_states": "动态状态",
    "relations": "人物关系",
    "events": "事件",
    "summaries": "摘要",
    "proposals": "记忆提案",
    "foreshadowing": "伏笔",
    "writing_goals": "字数目标",
    "quality_issues": "质量问题",
    "repair_candidates": "修复候选",
    "ai_tasks": "AI 任务",
    "model_configs": "模型配置",
}
_PLAN_STATUS = {"draft", "confirmed", "stale", "archived"}
_ARC_TYPES = {"main", "subplot", "character", "other"}
_ID_LIST_KEYS = {"participants", "character_entity_ids"}


class RowError(Exception):
    pass


class Counts:
    def __init__(self) -> None:
        self._values = {kind: 0 for kind in _KINDS}

    def bump(self, kind: str, amount: int = 1) -> None:
        self._values[kind] = self._values[kind] + amount

    def get(self, kind: str) -> int:
        return self._values[kind]

    def as_dict(self) -> dict[str, int]:
        return dict(self._values)

    def blocking(self) -> int:
        return sum(value for kind, value in self._values.items() if kind != "model_configs")


@dataclass
class PackagePlan:
    format_version: int
    novel_title: str
    can_import: bool
    message: str
    created: Counts
    skipped: Counts
    conflicts: Counts
    invalid: Counts
    warnings: list[str] = field(default_factory=list)
    invalid_reasons: list[str] = field(default_factory=list)
    conflict_map: dict[str, str] = field(default_factory=dict)
    novel: dict[str, object] | None = None
    volumes: list[dict[str, object]] = field(default_factory=list)
    chapters: list[dict[str, object]] = field(default_factory=list)
    versions: list[dict[str, object]] = field(default_factory=list)
    story_plan: dict[str, object] | None = None
    story_arcs: list[dict[str, object]] = field(default_factory=list)
    volume_outlines: list[dict[str, object]] = field(default_factory=list)
    outlines: list[dict[str, object]] = field(default_factory=list)
    scenes: list[dict[str, object]] = field(default_factory=list)
    entities: list[dict[str, object]] = field(default_factory=list)
    states: list[dict[str, object]] = field(default_factory=list)
    relations: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    summaries: list[dict[str, object]] = field(default_factory=list)
    proposals: list[dict[str, object]] = field(default_factory=list)
    foreshadowing: list[dict[str, object]] = field(default_factory=list)
    writing_goal: dict[str, object] | None = None
    issues: list[dict[str, object]] = field(default_factory=list)
    repairs: list[dict[str, object]] = field(default_factory=list)
    tasks: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class PortableFile:
    filename: str
    media_type: str
    body: bytes
    disposition: str


def export_novel_package(session: Session, novel_id: str) -> PortableFile:
    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    graph = _load_graph(session, novel)
    payload = _archive_bytes(graph)
    filename = _download_name(novel.title)
    logger.info("portable export novel_id=%s", novel.id)
    return PortableFile(
        filename=filename,
        media_type="application/zip",
        body=payload,
        disposition=_disposition(filename),
    )


def preview_package(session: Session, raw: bytes) -> PackagePlan:
    return prepare_package(session, raw)


def import_package(session: Session, raw: bytes) -> tuple[Novel, PackagePlan]:
    plan = prepare_package(session, raw)
    if not plan.can_import or plan.novel is None:
        raise PackageInvalid(plan.message)
    try:
        novel = _write_plan(session, plan)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("portable import failed")
        raise PackageImportFailed("导入没有完成，没有留下半成品。") from None
    session.refresh(novel)
    logger.info("portable import novel_id=%s", novel.id)
    return novel, plan


def prepare_package(session: Session, raw: bytes) -> PackagePlan:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PackageInvalid("作品包超过 64MB。没有写入任何数据。")
    archive = _open_zip(raw)
    _manifest(archive)
    catalog = _object_member(archive, "catalog.json")
    planning = _optional_object(archive, "planning.json")
    memory = _optional_object(archive, "memory.json")
    quality = _optional_object(archive, "quality.json")
    versions_doc = _optional_object(archive, "versions.json")
    ai_doc = _optional_object(archive, "ai.json")
    toc = _object_member(archive, "manuscript/toc.json")

    plan = PackagePlan(
        format_version=FORMAT_VERSION,
        novel_title="",
        can_import=False,
        message="",
        created=Counts(),
        skipped=Counts(),
        conflicts=Counts(),
        invalid=Counts(),
        warnings=[
            "模型 API Key 和访问口令不会导入。模型密钥需要在这台机器上重新配置。",
        ],
    )
    novel_row, novel_reason = _parse_novel(_required_object(catalog, "novel"))
    if novel_row is None:
        plan.invalid.bump("novels")
        plan.invalid_reasons.append(novel_reason or "作品记录无效。")
        plan.message = _refuse(plan.invalid_reasons[0])
        return plan
    if novel_row.pop("_deleted_ignored", None) is True:
        plan.warnings.append("包里的作品删除时间已忽略，导入后会出现在作品库。")
    plan.novel_title = _text_of(novel_row, "title")
    plan.novel = novel_row

    plan.volumes = _parse_many(catalog, "volumes", "volumes", _parse_volume, plan)
    plan.chapters = _parse_many(catalog, "chapters", "chapters", _parse_chapter, plan)
    plan.outlines = _parse_many(
        planning, "chapter_outlines", "chapter_outlines", _parse_outline, plan
    )
    plan.scenes = _parse_many(planning, "scene_cards", "scene_cards", _parse_scene, plan)
    plan.story_arcs = _parse_many(planning, "story_arcs", "story_arcs", _parse_story_arc, plan)
    plan.volume_outlines = _parse_many(
        planning, "volume_outlines", "volume_outlines", _parse_volume_outline, plan
    )
    _drop_duplicate_volume_outlines(plan)
    plan.entities = _parse_many(memory, "entities", "entities", _parse_entity, plan)
    plan.states = _parse_many(memory, "entity_states", "entity_states", _parse_state, plan)
    plan.relations = _parse_many(memory, "relations", "relations", _parse_relation, plan)
    plan.events = _parse_many(memory, "events", "events", _parse_event, plan)
    plan.summaries = _parse_many(memory, "summaries", "summaries", _parse_summary, plan)
    plan.proposals = _parse_many(memory, "proposals", "proposals", _parse_proposal, plan)
    plan.foreshadowing = _parse_many(
        quality, "foreshadowing", "foreshadowing", _parse_foreshadowing, plan
    )
    plan.issues = _parse_many(quality, "quality_issues", "quality_issues", _parse_issue, plan)
    plan.repairs = _parse_many(
        quality, "repair_candidates", "repair_candidates", _parse_repair, plan
    )
    plan.versions = _parse_many(
        versions_doc, "chapter_versions", "chapter_versions", _parse_version, plan
    )
    plan.tasks = _parse_many(ai_doc, "tasks", "ai_tasks", _parse_task, plan)
    if any(row.get("error_code") == "PORTABLE_IMPORT" for row in plan.tasks):
        plan.warnings.append("排队或生成中的 AI 任务已标为失败，不会在导入后继续生成。")
    plan.story_plan = _parse_optional(
        planning, "story_plan", "story_plans", _parse_story_plan, plan
    )
    plan.writing_goal = _parse_optional(quality, "writing_goal", "writing_goals", _parse_goal, plan)
    _skip_models(ai_doc, plan)
    _drop_duplicate_ids(plan)
    _drop_bad_versions(plan)
    _prune_links(plan)
    _check_toc(archive, toc, plan)
    if plan.invalid.blocking() == 0 and plan.novel is not None:
        _add_import_snapshots(plan)
        _allocate_ids(session, plan)
        plan.can_import = True
        plan.message = "可以导入为新作品，不会覆盖已有作品。"
    else:
        plan.can_import = False
        reason = plan.invalid_reasons[0] if plan.invalid_reasons else "作品包里有无效数据。"
        plan.message = _refuse(reason)
        plan.novel = None
    _fill_created(plan)
    return plan


def _write_plan(session: Session, plan: PackagePlan) -> Novel:
    novel_row = plan.novel
    if novel_row is None:
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    novel = Novel(
        id=_s(novel_row, "id"),
        title=_s(novel_row, "title"),
        genre=_opt_str(novel_row, "genre"),
        synopsis=_opt_str(novel_row, "synopsis"),
        style_guide=_opt_str(novel_row, "style_guide"),
        status=_s(novel_row, "status"),
        created_at=_dt(novel_row, "created_at"),
        updated_at=_dt(novel_row, "updated_at"),
        deleted_at=None,
    )
    session.add(novel)
    session.flush()
    for row in plan.volumes:
        session.add(
            Volume(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                title=_s(row, "title"),
                sort_order=_i(row, "sort_order"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    session.flush()
    for row in plan.chapters:
        session.add(
            Chapter(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                volume_id=_opt_str(row, "volume_id"),
                title=_s(row, "title"),
                sort_order=_i(row, "sort_order"),
                content=_obj(row, "content"),
                content_format=CANONICAL_CONTENT_FORMAT,
                content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
                word_count=_i(row, "word_count"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
                deleted_at=_opt_dt(row, "deleted_at"),
            )
        )
    session.flush()
    for row in plan.entities:
        session.add(
            StoryEntity(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                entity_type=_s(row, "entity_type"),
                name=_s(row, "name"),
                aliases=_str_list_value(row, "aliases"),
                profile=_obj(row, "profile"),
                status=_s(row, "status"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
                deleted_at=_opt_dt(row, "deleted_at"),
            )
        )
    session.flush()
    if plan.story_plan is not None:
        row = plan.story_plan
        session.add(
            StoryPlan(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                logline=_opt_str(row, "logline"),
                body=_opt_str(row, "body"),
                ending_intent=_opt_str(row, "ending_intent"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.story_arcs:
        session.add(
            StoryArc(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                arc_type=_s(row, "arc_type"),
                title=_s(row, "title"),
                summary=_opt_str(row, "summary"),
                thread_visibility=_opt_str(row, "thread_visibility"),
                sort_order=_i(row, "sort_order"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.volume_outlines:
        session.add(
            VolumeOutline(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                volume_id=_s(row, "volume_id"),
                goal=_opt_str(row, "goal"),
                key_events=_opt_str(row, "key_events"),
                start_state=_opt_str(row, "start_state"),
                end_state=_opt_str(row, "end_state"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.outlines:
        session.add(
            ChapterOutline(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_s(row, "chapter_id"),
                goal=_opt_str(row, "goal"),
                must_advance=_opt_str(row, "must_advance"),
                required_events=_opt_str(row, "required_events"),
                allowed_reveals=_opt_str(row, "allowed_reveals"),
                forbidden_reveals=_opt_str(row, "forbidden_reveals"),
                target_words=_opt_int(row, "target_words"),
                ending_hook=_opt_str(row, "ending_hook"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.proposals:
        session.add(
            MemoryChangeProposal(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                source_chapter_id=_s(row, "source_chapter_id"),
                source_revision=_i(row, "source_revision"),
                proposal_type=_s(row, "proposal_type"),
                payload=_obj(row, "payload"),
                evidence_quote=_s(row, "evidence_quote"),
                certainty=_s(row, "certainty"),
                status=_s(row, "status"),
                review_note=_opt_str(row, "review_note"),
                created_at=_dt(row, "created_at"),
                reviewed_at=_opt_dt(row, "reviewed_at"),
            )
        )
    session.flush()
    for row in plan.states:
        session.add(
            EntityState(
                id=_s(row, "id"),
                entity_id=_s(row, "entity_id"),
                chapter_id=_s(row, "chapter_id"),
                source_revision=_opt_int(row, "source_revision"),
                proposal_id=_opt_str(row, "proposal_id"),
                state_data=_obj(row, "state_data"),
                evidence_quote=_opt_str(row, "evidence_quote"),
                source_type=_s(row, "source_type"),
                valid_from_text=_opt_str(row, "valid_from_text"),
                valid_until_text=_opt_str(row, "valid_until_text"),
                created_at=_dt(row, "created_at"),
            )
        )
    for row in plan.events:
        session.add(
            StoryEvent(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_s(row, "chapter_id"),
                source_revision=_opt_int(row, "source_revision"),
                proposal_id=_opt_str(row, "proposal_id"),
                event_time_text=_opt_str(row, "event_time_text"),
                description=_s(row, "description"),
                participants=_str_list_value(row, "participants"),
                evidence_quote=_s(row, "evidence_quote"),
                certainty=_s(row, "certainty"),
                created_at=_dt(row, "created_at"),
                deleted_at=_opt_dt(row, "deleted_at"),
            )
        )
    for row in plan.relations:
        session.add(
            EntityRelation(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                from_entity_id=_s(row, "from_entity_id"),
                to_entity_id=_s(row, "to_entity_id"),
                relation_type=_s(row, "relation_type"),
                story_time_text=_opt_str(row, "story_time_text"),
                storyline=_opt_str(row, "storyline"),
                source_chapter_id=_opt_str(row, "source_chapter_id"),
                source_revision=_opt_int(row, "source_revision"),
                evidence_quote=_opt_str(row, "evidence_quote"),
                status=_s(row, "status"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
                deleted_at=_opt_dt(row, "deleted_at"),
            )
        )
    for row in plan.summaries:
        session.add(
            ChapterSummary(
                id=_s(row, "id"),
                chapter_id=_s(row, "chapter_id"),
                summary=_s(row, "summary"),
                key_facts=_str_list_value(row, "key_facts"),
                source_revision=_i(row, "source_revision"),
                model_name=_opt_str(row, "model_name"),
                status=_s(row, "status"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.scenes:
        session.add(
            SceneCard(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_s(row, "chapter_id"),
                sort_order=_i(row, "sort_order"),
                goal=_opt_str(row, "goal"),
                location_entity_id=_opt_str(row, "location_entity_id"),
                character_entity_ids=_str_list_value(row, "character_entity_ids"),
                conflict=_opt_str(row, "conflict"),
                turning_point=_opt_str(row, "turning_point"),
                expected_outcome=_opt_str(row, "expected_outcome"),
                must_convey=_opt_str(row, "must_convey"),
                must_not_reveal=_opt_str(row, "must_not_reveal"),
                status=_s(row, "status"),
                revision=_i(row, "revision"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.foreshadowing:
        session.add(
            Foreshadowing(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                introduced_chapter_id=_s(row, "introduced_chapter_id"),
                description=_s(row, "description"),
                status=_s(row, "status"),
                payoff_chapter_id=_opt_str(row, "payoff_chapter_id"),
                evidence_quote=_opt_str(row, "evidence_quote"),
                event_time_text=_opt_str(row, "event_time_text"),
                character_discovered_text=_opt_str(row, "character_discovered_text"),
                reader_revealed_text=_opt_str(row, "reader_revealed_text"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    if plan.writing_goal is not None:
        row = plan.writing_goal
        session.add(
            WritingGoal(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                target_words=_i(row, "target_words"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    session.flush()
    for row in plan.issues:
        session.add(
            QualityIssue(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_s(row, "chapter_id"),
                issue_type=_s(row, "issue_type"),
                severity=_s(row, "severity"),
                confidence=_i(row, "confidence"),
                status=_s(row, "status"),
                manuscript_snippet=_s(row, "manuscript_snippet"),
                target_revision=_opt_int(row, "target_revision"),
                location_note=_opt_str(row, "location_note"),
                evidence_status=_s(row, "evidence_status"),
                evidence=_dict_list(row, "evidence"),
                related_refs=_dict_list(row, "related_refs"),
                rule_id=_s(row, "rule_id"),
                rule_version=_s(row, "rule_version"),
                analysis_version=_opt_str(row, "analysis_version"),
                provider_mode=_s(row, "provider_mode"),
                suggested_action=_s(row, "suggested_action"),
                finding_class=_s(row, "finding_class"),
                fingerprint=_s(row, "fingerprint"),
                fixed_revision=_opt_int(row, "fixed_revision"),
                recheck_count=_i(row, "recheck_count"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    session.flush()
    for row in plan.repairs:
        session.add(
            QualityRepairCandidate(
                id=_s(row, "id"),
                issue_id=_s(row, "issue_id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_s(row, "chapter_id"),
                target_revision=_i(row, "target_revision"),
                apply_mode=_s(row, "apply_mode"),
                applicable=_b(row, "applicable"),
                original_snippet=_s(row, "original_snippet"),
                replacement_text=_s(row, "replacement_text"),
                rationale=_s(row, "rationale"),
                diff_preview=_s(row, "diff_preview"),
                provider_mode=_s(row, "provider_mode"),
                prompt_version=_s(row, "prompt_version"),
                status=_s(row, "status"),
                created_at=_dt(row, "created_at"),
                updated_at=_dt(row, "updated_at"),
            )
        )
    for row in plan.tasks:
        session.add(
            AiTask(
                id=_s(row, "id"),
                novel_id=_s(row, "novel_id"),
                chapter_id=_opt_str(row, "chapter_id"),
                task_type=_s(row, "task_type"),
                status=_s(row, "status"),
                model_config_id=None,
                input_snapshot=_obj(row, "input_snapshot"),
                prompt_version=_s(row, "prompt_version"),
                output_text=_opt_str(row, "output_text"),
                error_code=_opt_str(row, "error_code"),
                error_message_safe=_opt_str(row, "error_message_safe"),
                input_tokens=_opt_int(row, "input_tokens"),
                output_tokens=_opt_int(row, "output_tokens"),
                resolution=_opt_str(row, "resolution"),
                started_at=_opt_dt(row, "started_at"),
                finished_at=_opt_dt(row, "finished_at"),
                created_at=_dt(row, "created_at"),
            )
        )
    session.flush()
    for row in plan.versions:
        session.add(
            ChapterVersion(
                id=_s(row, "id"),
                chapter_id=_s(row, "chapter_id"),
                revision=_i(row, "revision"),
                content_snapshot=_obj(row, "content_snapshot"),
                content_format=CANONICAL_CONTENT_FORMAT,
                content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
                change_source=_s(row, "change_source"),
                change_note=_opt_str(row, "change_note"),
                ai_task_id=_opt_str(row, "ai_task_id"),
                repair_candidate_id=_opt_str(row, "repair_candidate_id"),
                created_at=_dt(row, "created_at"),
            )
        )
    session.flush()
    return novel


def _load_graph(session: Session, novel: Novel) -> dict[str, object]:
    volumes = catalog_repo.list_volumes(session, novel.id)
    chapters = list(session.scalars(select(Chapter).where(Chapter.novel_id == novel.id)).all())
    chapter_ids = [chapter.id for chapter in chapters]
    entities = list(
        session.scalars(select(StoryEntity).where(StoryEntity.novel_id == novel.id)).all()
    )
    entity_ids = [entity.id for entity in entities]
    versions = _ids_query(session, ChapterVersion, ChapterVersion.chapter_id, chapter_ids)
    states = _ids_query(session, EntityState, EntityState.entity_id, entity_ids)
    summaries = _ids_query(session, ChapterSummary, ChapterSummary.chapter_id, chapter_ids)
    tasks = list(session.scalars(select(AiTask).where(AiTask.novel_id == novel.id)).all())
    model_ids = [task.model_config_id for task in tasks if task.model_config_id]
    models = _ids_query(session, ModelConfig, ModelConfig.id, model_ids)
    return {
        "novel": novel,
        "volumes": volumes,
        "chapters": chapters,
        "versions": versions,
        "story_plan": session.scalar(select(StoryPlan).where(StoryPlan.novel_id == novel.id)),
        "story_arcs": list(
            session.scalars(
                select(StoryArc)
                .where(StoryArc.novel_id == novel.id)
                .order_by(StoryArc.sort_order.asc(), StoryArc.id.asc())
            ).all()
        ),
        "volume_outlines": list(
            session.scalars(select(VolumeOutline).where(VolumeOutline.novel_id == novel.id)).all()
        ),
        "outlines": list(
            session.scalars(select(ChapterOutline).where(ChapterOutline.novel_id == novel.id)).all()
        ),
        "scenes": list(
            session.scalars(select(SceneCard).where(SceneCard.novel_id == novel.id)).all()
        ),
        "entities": entities,
        "states": states,
        "relations": list(
            session.scalars(select(EntityRelation).where(EntityRelation.novel_id == novel.id)).all()
        ),
        "events": list(
            session.scalars(select(StoryEvent).where(StoryEvent.novel_id == novel.id)).all()
        ),
        "summaries": summaries,
        "proposals": list(
            session.scalars(
                select(MemoryChangeProposal).where(MemoryChangeProposal.novel_id == novel.id)
            ).all()
        ),
        "foreshadowing": list(
            session.scalars(select(Foreshadowing).where(Foreshadowing.novel_id == novel.id)).all()
        ),
        "writing_goal": session.scalar(select(WritingGoal).where(WritingGoal.novel_id == novel.id)),
        "issues": list(
            session.scalars(select(QualityIssue).where(QualityIssue.novel_id == novel.id)).all()
        ),
        "repairs": list(
            session.scalars(
                select(QualityRepairCandidate).where(QualityRepairCandidate.novel_id == novel.id)
            ).all()
        ),
        "tasks": tasks,
        "models": models,
    }


def _archive_bytes(graph: dict[str, object]) -> bytes:
    novel = cast(Novel, graph["novel"])
    volumes = cast(list[Volume], graph["volumes"])
    chapters = cast(list[Chapter], graph["chapters"])
    live = _live_order(volumes, [chapter for chapter in chapters if chapter.deleted_at is None])
    volume_titles = {volume.id: volume.title for volume in volumes}
    toc_entries: list[dict[str, object]] = []
    files: dict[str, str] = {}
    for index, chapter in enumerate(live, start=1):
        markdown_name = f"manuscript/{index:04d}.md"
        text_name = f"manuscript/{index:04d}.txt"
        document = _as_document(chapter.content)
        files[markdown_name] = document_to_markdown(document)
        files[text_name] = document_to_plain(document)
        heading = volume_titles.get(chapter.volume_id or "", "未分卷")
        if chapter.volume_id is None:
            heading = "未分卷"
        toc_entries.append(
            {
                "position": index,
                "chapter_id": chapter.id,
                "title": chapter.title,
                "volume_title": heading,
                "markdown": markdown_name,
                "text": text_name,
            }
        )
    story_plan = cast(StoryPlan | None, graph["story_plan"])
    writing_goal = cast(WritingGoal | None, graph["writing_goal"])
    members: dict[str, object] = {
        "manifest.json": {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "exported_at": _dump_dt(datetime.now(UTC)),
            "novel_id": novel.id,
            "novel_title": novel.title,
            "content_format": CANONICAL_CONTENT_FORMAT,
            "content_format_version": CANONICAL_CONTENT_FORMAT_VERSION,
            "notes": [
                "Markdown 与 TXT 是按目录顺序排列的可读正文。导入以 JSON 里的 Tiptap 正文为准。",
                "不含模型 API Key、密钥密文或访问口令。模型需要重新配置。",
            ],
        },
        "catalog.json": {
            "novel": _novel_dict(novel),
            "volumes": [_volume_dict(volume) for volume in volumes],
            "chapters": [_chapter_dict(chapter) for chapter in chapters],
        },
        "planning.json": {
            "story_plan": None if story_plan is None else _story_plan_dict(story_plan),
            "story_arcs": [
                _story_arc_dict(row) for row in cast(list[StoryArc], graph["story_arcs"])
            ],
            "volume_outlines": [
                _volume_outline_dict(row)
                for row in cast(list[VolumeOutline], graph["volume_outlines"])
            ],
            "chapter_outlines": [
                _outline_dict(row) for row in cast(list[ChapterOutline], graph["outlines"])
            ],
            "scene_cards": [_scene_dict(row) for row in cast(list[SceneCard], graph["scenes"])],
        },
        "memory.json": {
            "entities": [_entity_dict(row) for row in cast(list[StoryEntity], graph["entities"])],
            "entity_states": [_state_dict(row) for row in cast(list[EntityState], graph["states"])],
            "relations": [
                _relation_dict(row) for row in cast(list[EntityRelation], graph["relations"])
            ],
            "events": [_event_dict(row) for row in cast(list[StoryEvent], graph["events"])],
            "summaries": [
                _summary_dict(row) for row in cast(list[ChapterSummary], graph["summaries"])
            ],
            "proposals": [
                _proposal_dict(row) for row in cast(list[MemoryChangeProposal], graph["proposals"])
            ],
        },
        "quality.json": {
            "foreshadowing": [
                _foreshadowing_dict(row)
                for row in cast(list[Foreshadowing], graph["foreshadowing"])
            ],
            "writing_goal": None if writing_goal is None else _goal_dict(writing_goal),
            "quality_issues": [
                _issue_dict(row) for row in cast(list[QualityIssue], graph["issues"])
            ],
            "repair_candidates": [
                _repair_dict(row) for row in cast(list[QualityRepairCandidate], graph["repairs"])
            ],
        },
        "versions.json": {
            "chapter_versions": [
                _version_dict(row) for row in cast(list[ChapterVersion], graph["versions"])
            ]
        },
        "ai.json": {
            "tasks": [_task_dict(row) for row in cast(list[AiTask], graph["tasks"])],
            "model_configs": [_model_dict(row) for row in cast(list[ModelConfig], graph["models"])],
        },
        "manuscript/toc.json": {"entries": toc_entries},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, _dumps(strip_secrets(body)))
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def strip_secrets(value: object) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SECRET_KEYS:
                continue
            cleaned[key] = strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    return value


def _open_zip(raw: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise PackageInvalid("作品包格式无法识别。请使用导出的作品包。没有写入任何数据。") from exc
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise PackageInvalid("作品包文件过多。没有写入任何数据。")
    total = 0
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in name.split("/") or name in seen:
            raise PackageInvalid("作品包路径无法识别。没有写入任何数据。")
        seen.add(name)
        if info.file_size > MAX_MEMBER_BYTES:
            raise PackageInvalid("作品包里有过大的文件。没有写入任何数据。")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise PackageInvalid("作品包解压后过大。没有写入任何数据。")
    return archive


def _manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    payload = _object_member(archive, "manifest.json")
    marker = payload.get("format")
    version = payload.get("format_version")
    if marker != FORMAT:
        raise UnsupportedPackage(
            "作品包格式无法识别。当前只接受 ai-novel-writer-portable-v1。没有写入任何数据。"
        )
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnsupportedPackage("作品包的格式版本无法识别。当前只接受版本 1。没有写入任何数据。")
    if version != FORMAT_VERSION:
        raise UnsupportedPackage(
            f"不支持的作品包格式版本：{version}。当前只接受版本 1"
            "（ai-novel-writer-portable-v1）。没有写入任何数据。"
        )
    return payload


def _object_member(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    try:
        raw = archive.read(name)
    except KeyError as exc:
        raise PackageInvalid(f"作品包缺少 {name}。没有写入任何数据。") from exc
    return _json_object(raw, name)


def _optional_object(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    try:
        raw = archive.read(name)
    except KeyError:
        return {}
    return _json_object(raw, name)


def _json_object(raw: bytes, name: str) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageInvalid(f"作品包里的 {name} 无法读取。没有写入任何数据。") from exc
    if not isinstance(payload, dict):
        raise PackageInvalid(f"作品包里的 {name} 无法读取。没有写入任何数据。")
    return cast(dict[str, object], payload)


def _required_object(payload: dict[str, object], key: str) -> object:
    return payload.get(key)


def _parse_many(
    payload: dict[str, object],
    key: str,
    kind: str,
    parser: Callable[[object], dict[str, object]],
    plan: PackagePlan,
) -> list[dict[str, object]]:
    raw = payload.get(key, [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise PackageInvalid(f"作品包里的{_LABELS[kind]}列表无法读取。没有写入任何数据。")
    if len(raw) > MAX_ROWS:
        raise PackageInvalid("作品包记录过多。没有写入任何数据。")
    rows: list[dict[str, object]] = []
    for item in raw:
        try:
            rows.append(parser(item))
        except RowError as exc:
            plan.invalid.bump(kind)
            _reason(plan, kind, str(exc))
    return rows


def _parse_optional(
    payload: dict[str, object],
    key: str,
    kind: str,
    parser: Callable[[object], dict[str, object]],
    plan: PackagePlan,
) -> dict[str, object] | None:
    if key not in payload or payload.get(key) is None:
        return None
    try:
        return parser(payload.get(key))
    except RowError as exc:
        plan.invalid.bump(kind)
        _reason(plan, kind, str(exc))
        return None


def _skip_models(payload: dict[str, object], plan: PackagePlan) -> None:
    raw = payload.get("model_configs", [])
    if raw is None:
        return
    if not isinstance(raw, list):
        plan.invalid.bump("model_configs")
        _reason(plan, "model_configs", "列表无法读取，已跳过，不会写入模型配置。")
        return
    for item in raw:
        plan.skipped.bump("model_configs")
        if not isinstance(item, dict):
            plan.invalid.bump("model_configs")


def _parse_novel(raw: object) -> tuple[dict[str, object] | None, str | None]:
    try:
        if not isinstance(raw, dict):
            raise RowError("缺少作品记录")
        deleted = raw.get("deleted_at")
        row: dict[str, object] = {
            "id": _id(raw.get("id"), required=True),
            "title": _text(raw.get("title"), max_len=200, required=True, strip=True),
            "genre": _text(raw.get("genre"), max_len=100, required=False),
            "synopsis": _text(raw.get("synopsis"), max_len=MAX_TEXT, required=False),
            "style_guide": _text(raw.get("style_guide"), max_len=MAX_TEXT, required=False),
            "status": _enum(raw.get("status"), {"draft", "active", "archived"}),
            "created_at": _when(raw.get("created_at"), required=True),
            "updated_at": _when(raw.get("updated_at"), required=True),
        }
        if deleted not in (None, ""):
            row["_deleted_ignored"] = True
        return row, None
    except RowError as exc:
        return None, f"作品：{exc}"


def _parse_volume(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "title": _text(body.get("title"), max_len=200, required=True, strip=True),
        "sort_order": _number(body.get("sort_order"), minimum=0),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_chapter(raw: object) -> dict[str, object]:
    body = _record(raw)
    if body.get("content_format") != CANONICAL_CONTENT_FORMAT:
        raise RowError("正文格式不是 tiptap_json")
    if body.get("content_format_version") != CANONICAL_CONTENT_FORMAT_VERSION:
        raise RowError("正文格式版本不受支持")
    document = _document(body.get("content"))
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "volume_id": _id(body.get("volume_id"), required=False),
        "title": _text(body.get("title"), max_len=200, required=True, strip=True),
        "sort_order": _number(body.get("sort_order"), minimum=0),
        "content": document,
        "word_count": word_count(document),
        "status": _enum(body.get("status"), {"outline", "draft", "revised", "final"}),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
        "deleted_at": _when(body.get("deleted_at"), required=False),
    }


def _parse_version(raw: object) -> dict[str, object]:
    body = _record(raw)
    if body.get("content_format") not in (None, CANONICAL_CONTENT_FORMAT):
        raise RowError("版本正文格式不是 tiptap_json")
    return {
        "id": _id(body.get("id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "revision": _number(body.get("revision"), minimum=1),
        "content_snapshot": _document(body.get("content_snapshot")),
        "change_source": _enum(
            body.get("change_source"),
            {"manual", "ai_accepted", "restore", "import"},
        ),
        "change_note": _text(body.get("change_note"), max_len=MAX_TEXT, required=False),
        "ai_task_id": _id(body.get("ai_task_id"), required=False),
        "repair_candidate_id": _id(body.get("repair_candidate_id"), required=False),
        "created_at": _when(body.get("created_at"), required=True),
    }


def _parse_story_plan(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "logline": _text(body.get("logline"), max_len=MAX_TEXT, required=False),
        "body": _text(body.get("body"), max_len=MAX_TEXT, required=False),
        "ending_intent": _text(body.get("ending_intent"), max_len=MAX_TEXT, required=False),
        "status": _enum(body.get("status"), _PLAN_STATUS),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_story_arc(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "arc_type": _enum(body.get("arc_type"), _ARC_TYPES),
        "title": _text(body.get("title"), max_len=200, required=True),
        "summary": _text(body.get("summary"), max_len=MAX_TEXT, required=False),
        "thread_visibility": _optional_enum(body.get("thread_visibility"), {"surface", "hidden"}),
        "sort_order": _number(body.get("sort_order"), minimum=0),
        "status": _enum(body.get("status"), _PLAN_STATUS),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_volume_outline(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "volume_id": _id(body.get("volume_id"), required=True),
        "goal": _text(body.get("goal"), max_len=MAX_TEXT, required=False),
        "key_events": _text(body.get("key_events"), max_len=MAX_TEXT, required=False),
        "start_state": _text(body.get("start_state"), max_len=MAX_TEXT, required=False),
        "end_state": _text(body.get("end_state"), max_len=MAX_TEXT, required=False),
        "status": _enum(body.get("status"), _PLAN_STATUS),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _drop_duplicate_volume_outlines(plan: PackagePlan) -> None:
    seen: set[str] = set()
    kept: list[dict[str, object]] = []
    for row in plan.volume_outlines:
        volume_id = _text_of(row, "volume_id")
        if volume_id in seen:
            plan.invalid.bump("volume_outlines")
            _reason(plan, "volume_outlines", "同一卷有多份卷大纲")
            continue
        seen.add(volume_id)
        kept.append(row)
    plan.volume_outlines = kept


def _parse_outline(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "goal": _text(body.get("goal"), max_len=MAX_TEXT, required=False),
        "must_advance": _text(body.get("must_advance"), max_len=MAX_TEXT, required=False),
        "required_events": _text(body.get("required_events"), max_len=MAX_TEXT, required=False),
        "allowed_reveals": _text(body.get("allowed_reveals"), max_len=MAX_TEXT, required=False),
        "forbidden_reveals": _text(body.get("forbidden_reveals"), max_len=MAX_TEXT, required=False),
        "target_words": _optional_number(body.get("target_words"), minimum=1),
        "ending_hook": _text(body.get("ending_hook"), max_len=MAX_TEXT, required=False),
        "status": _enum(body.get("status"), _PLAN_STATUS),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_scene(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "sort_order": _number(body.get("sort_order"), minimum=0),
        "goal": _text(body.get("goal"), max_len=MAX_TEXT, required=False),
        "location_entity_id": _id(body.get("location_entity_id"), required=False),
        "character_entity_ids": _id_list(body.get("character_entity_ids")),
        "conflict": _text(body.get("conflict"), max_len=MAX_TEXT, required=False),
        "turning_point": _text(body.get("turning_point"), max_len=MAX_TEXT, required=False),
        "expected_outcome": _text(body.get("expected_outcome"), max_len=MAX_TEXT, required=False),
        "must_convey": _text(body.get("must_convey"), max_len=MAX_TEXT, required=False),
        "must_not_reveal": _text(body.get("must_not_reveal"), max_len=MAX_TEXT, required=False),
        "status": _enum(body.get("status"), _PLAN_STATUS),
        "revision": _number(body.get("revision"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_entity(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "entity_type": _enum(
            body.get("entity_type"),
            {"character", "location", "organization", "item", "rule", "other"},
        ),
        "name": _text(body.get("name"), max_len=200, required=True, strip=True),
        "aliases": _plain_list(body.get("aliases"), max_len=200, max_items=40),
        "profile": _json_size(body.get("profile"), max_chars=100_000),
        "status": _enum(body.get("status"), {"active", "inactive", "unknown"}),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
        "deleted_at": _when(body.get("deleted_at"), required=False),
    }


def _parse_state(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "entity_id": _id(body.get("entity_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "source_revision": _optional_number(body.get("source_revision"), minimum=1),
        "proposal_id": _id(body.get("proposal_id"), required=False),
        "state_data": _json_size(body.get("state_data"), max_chars=100_000),
        "evidence_quote": _text(body.get("evidence_quote"), max_len=MAX_TEXT, required=False),
        "source_type": _enum(body.get("source_type"), {"manual", "ai_proposal", "import"}),
        "valid_from_text": _text(body.get("valid_from_text"), max_len=200, required=False),
        "valid_until_text": _text(body.get("valid_until_text"), max_len=200, required=False),
        "created_at": _when(body.get("created_at"), required=True),
    }


def _parse_relation(raw: object) -> dict[str, object]:
    body = _record(raw)
    source = _id(body.get("from_entity_id"), required=True)
    target = _id(body.get("to_entity_id"), required=True)
    if source == target:
        raise RowError("关系的两端不能是同一个设定")
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "from_entity_id": source,
        "to_entity_id": target,
        "relation_type": _text(body.get("relation_type"), max_len=80, required=True, strip=True),
        "story_time_text": _text(body.get("story_time_text"), max_len=200, required=False),
        "storyline": _text(body.get("storyline"), max_len=80, required=False),
        "source_chapter_id": _id(body.get("source_chapter_id"), required=False),
        "source_revision": _optional_number(body.get("source_revision"), minimum=1),
        "evidence_quote": _text(body.get("evidence_quote"), max_len=MAX_TEXT, required=False),
        "status": _enum(body.get("status"), {"active", "ended", "unknown"}),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
        "deleted_at": _when(body.get("deleted_at"), required=False),
    }


def _parse_event(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "source_revision": _optional_number(body.get("source_revision"), minimum=1),
        "proposal_id": _id(body.get("proposal_id"), required=False),
        "event_time_text": _text(body.get("event_time_text"), max_len=200, required=False),
        "description": _text(body.get("description"), max_len=MAX_TEXT, required=True, strip=True),
        "participants": _id_list(body.get("participants")),
        "evidence_quote": _text(body.get("evidence_quote"), max_len=MAX_TEXT, required=True),
        "certainty": _enum(body.get("certainty"), {"confirmed", "inferred", "uncertain"}),
        "created_at": _when(body.get("created_at"), required=True),
        "deleted_at": _when(body.get("deleted_at"), required=False),
    }


def _parse_summary(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "summary": _text(body.get("summary"), max_len=MAX_TEXT, required=True),
        "key_facts": _plain_list(body.get("key_facts"), max_len=2000, max_items=200),
        "source_revision": _number(body.get("source_revision"), minimum=1),
        "model_name": _text(body.get("model_name"), max_len=200, required=False),
        "status": _enum(body.get("status"), {"current", "stale", "rejected"}),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_proposal(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "source_chapter_id": _id(body.get("source_chapter_id"), required=True),
        "source_revision": _number(body.get("source_revision"), minimum=1),
        "proposal_type": _enum(
            body.get("proposal_type"),
            {
                "entity_create",
                "entity_update",
                "entity_state",
                "story_event",
                "chapter_summary",
                "entity_relation",
                "foreshadowing",
                "setting_supplement",
                "potential_conflict",
            },
        ),
        "payload": _json_size(body.get("payload"), max_chars=500_000),
        "evidence_quote": _text(body.get("evidence_quote"), max_len=MAX_TEXT, required=True),
        "certainty": _enum(body.get("certainty"), {"confirmed", "inferred", "uncertain"}),
        "status": _enum(
            body.get("status"),
            {"pending", "accepted", "rejected", "reverted", "stale", "deferred", "intentional"},
        ),
        "review_note": _text(body.get("review_note"), max_len=MAX_TEXT, required=False),
        "created_at": _when(body.get("created_at"), required=True),
        "reviewed_at": _when(body.get("reviewed_at"), required=False),
    }


def _parse_foreshadowing(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "introduced_chapter_id": _id(body.get("introduced_chapter_id"), required=True),
        "description": _text(body.get("description"), max_len=MAX_TEXT, required=True, strip=True),
        "status": _enum(
            body.get("status"),
            {"open", "planned", "resolved", "abandoned", "uncertain"},
        ),
        "payoff_chapter_id": _id(body.get("payoff_chapter_id"), required=False),
        "evidence_quote": _text(body.get("evidence_quote"), max_len=MAX_TEXT, required=False),
        "event_time_text": _text(body.get("event_time_text"), max_len=200, required=False),
        "character_discovered_text": _text(
            body.get("character_discovered_text"), max_len=200, required=False
        ),
        "reader_revealed_text": _text(
            body.get("reader_revealed_text"), max_len=200, required=False
        ),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_goal(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "target_words": _number(body.get("target_words"), minimum=1),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_issue(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "issue_type": _enum(
            body.get("issue_type"),
            {
                "fact_continuity",
                "time_continuity",
                "character_continuity",
                "foreshadowing",
                "outline_execution",
                "text_surface",
            },
        ),
        "severity": _enum(body.get("severity"), {"low", "medium", "high"}),
        "confidence": _number(body.get("confidence"), minimum=0, maximum=100),
        "status": _enum(
            body.get("status"),
            {"pending", "confirmed", "ignored", "fixed", "expired", "deferred", "intentional"},
        ),
        "finding_class": _enum(
            body.get("finding_class", "suspected"),
            {"deterministic", "suspected", "creative_risk"},
        ),
        "manuscript_snippet": _text(
            body.get("manuscript_snippet"), max_len=MAX_TEXT, required=True
        ),
        "target_revision": _optional_number(body.get("target_revision"), minimum=1),
        "location_note": _text(body.get("location_note"), max_len=MAX_TEXT, required=False),
        "evidence_status": _enum(body.get("evidence_status"), {"sufficient", "insufficient"}),
        "evidence": _dict_items(body.get("evidence")),
        "related_refs": _dict_items(body.get("related_refs")),
        "rule_id": _text(body.get("rule_id"), max_len=80, required=True),
        "rule_version": _text(body.get("rule_version"), max_len=64, required=True),
        "analysis_version": _text(body.get("analysis_version"), max_len=64, required=False),
        "provider_mode": _enum(body.get("provider_mode"), {"rule", "mock", "openai_compatible"}),
        "suggested_action": _text(body.get("suggested_action"), max_len=MAX_TEXT, required=True),
        "fingerprint": _text(body.get("fingerprint"), max_len=64, required=True),
        "fixed_revision": _optional_number(body.get("fixed_revision"), minimum=1),
        "recheck_count": _number(body.get("recheck_count"), minimum=0),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_repair(raw: object) -> dict[str, object]:
    body = _record(raw)
    return {
        "id": _id(body.get("id"), required=True),
        "issue_id": _id(body.get("issue_id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=True),
        "target_revision": _number(body.get("target_revision"), minimum=1),
        "apply_mode": _enum(body.get("apply_mode"), {"replace_selection", "append"}),
        "applicable": _bool(body.get("applicable")),
        "original_snippet": _text(body.get("original_snippet"), max_len=MAX_TEXT, required=True),
        "replacement_text": _text(body.get("replacement_text"), max_len=MAX_TEXT, required=True),
        "rationale": _text(body.get("rationale"), max_len=MAX_TEXT, required=True),
        "diff_preview": _text(body.get("diff_preview"), max_len=MAX_TEXT, required=True),
        "provider_mode": _enum(body.get("provider_mode"), {"rule", "mock", "openai_compatible"}),
        "prompt_version": _text(body.get("prompt_version"), max_len=64, required=True),
        "status": _enum(body.get("status"), {"proposed", "accepted", "rejected", "conflict"}),
        "created_at": _when(body.get("created_at"), required=True),
        "updated_at": _when(body.get("updated_at"), required=True),
    }


def _parse_task(raw: object) -> dict[str, object]:
    body = _record(raw)
    status = _enum(body.get("status"), {"queued", "running", "completed", "failed", "cancelled"})
    error_code = _text(body.get("error_code"), max_len=64, required=False)
    error_message = _text(body.get("error_message_safe"), max_len=MAX_TEXT, required=False)
    if status in {"queued", "running"}:
        status = "failed"
        error_code = "PORTABLE_IMPORT"
        error_message = "这是从作品包导入的任务，不会在这台机器上继续生成。"
    return {
        "id": _id(body.get("id"), required=True),
        "novel_id": _id(body.get("novel_id"), required=True),
        "chapter_id": _id(body.get("chapter_id"), required=False),
        "task_type": _enum(
            body.get("task_type"),
            {"continue", "rewrite", "polish", "expand", "shrink", "proofread"},
        ),
        "status": status,
        "model_config_id": _id(body.get("model_config_id"), required=False),
        "input_snapshot": _json_size(body.get("input_snapshot"), max_chars=1_500_000),
        "prompt_version": _text(body.get("prompt_version"), max_len=32, required=True),
        "output_text": _text(body.get("output_text"), max_len=MAX_TEXT, required=False),
        "error_code": error_code,
        "error_message_safe": error_message,
        "input_tokens": _optional_number(body.get("input_tokens"), minimum=0),
        "output_tokens": _optional_number(body.get("output_tokens"), minimum=0),
        "resolution": _optional_enum(body.get("resolution"), {"accepted", "rejected"}),
        "started_at": _when(body.get("started_at"), required=False),
        "finished_at": _when(body.get("finished_at"), required=False),
        "created_at": _when(body.get("created_at"), required=True),
    }


def _grouped_rows(plan: PackagePlan) -> list[tuple[str, list[dict[str, object]]]]:
    groups: list[tuple[str, list[dict[str, object]]]] = [
        ("volumes", plan.volumes),
        ("chapters", plan.chapters),
        ("chapter_versions", plan.versions),
        ("chapter_outlines", plan.outlines),
        ("scene_cards", plan.scenes),
        ("story_arcs", plan.story_arcs),
        ("volume_outlines", plan.volume_outlines),
        ("entities", plan.entities),
        ("entity_states", plan.states),
        ("relations", plan.relations),
        ("events", plan.events),
        ("summaries", plan.summaries),
        ("proposals", plan.proposals),
        ("foreshadowing", plan.foreshadowing),
        ("quality_issues", plan.issues),
        ("repair_candidates", plan.repairs),
        ("ai_tasks", plan.tasks),
    ]
    if plan.story_plan is not None:
        groups.append(("story_plans", [plan.story_plan]))
    if plan.writing_goal is not None:
        groups.append(("writing_goals", [plan.writing_goal]))
    if plan.novel is not None:
        groups.append(("novels", [plan.novel]))
    return groups


def _drop_duplicate_ids(plan: PackagePlan) -> None:
    seen: dict[str, str] = {}
    duplicates: set[str] = set()
    for kind, rows in _grouped_rows(plan):
        for row in rows:
            source = _text_of(row, "id")
            if source in seen:
                duplicates.add(source)
            else:
                seen[source] = kind
    if not duplicates:
        return
    for kind, rows in _grouped_rows(plan):
        kept: list[dict[str, object]] = []
        for row in rows:
            if _text_of(row, "id") in duplicates:
                plan.invalid.bump(kind)
                _reason(plan, kind, "编号在作品包里重复")
            else:
                kept.append(row)
        rows[:] = kept
        _write_back_singletons(plan, kind, rows)


def _drop_bad_versions(plan: PackagePlan) -> None:
    revisions = {_text_of(chapter, "id"): _int_of(chapter, "revision") for chapter in plan.chapters}
    seen: set[tuple[str, int]] = set()
    kept: list[dict[str, object]] = []
    for row in plan.versions:
        chapter_id = _text_of(row, "chapter_id")
        revision = _int_of(row, "revision")
        limit = revisions.get(chapter_id)
        if limit is None or revision > limit or (chapter_id, revision) in seen:
            plan.invalid.bump("chapter_versions")
            _reason(plan, "chapter_versions", "修订号超出当前正文，或同一章出现重复修订")
            continue
        seen.add((chapter_id, revision))
        kept.append(row)
    plan.versions = kept


def _prune_links(plan: PackagePlan) -> None:
    if plan.novel is None:
        return
    novel_id = _text_of(plan.novel, "id")
    for _ in range(12):
        indexes = _link_index(plan, novel_id)
        dropped = False
        for kind, rows in _grouped_rows(plan):
            if kind == "novels":
                continue
            kept: list[dict[str, object]] = []
            for row in rows:
                problem = _link_problem(row, indexes)
                if problem is None:
                    kept.append(row)
                else:
                    dropped = True
                    plan.invalid.bump(kind)
                    _reason(plan, kind, problem)
            rows[:] = kept
            _write_back_singletons(plan, kind, rows)
        if not dropped:
            return


def _link_index(plan: PackagePlan, novel_id: str) -> dict[str, set[str]]:
    def ids(rows: list[dict[str, object]]) -> set[str]:
        return {_text_of(row, "id") for row in rows}

    package = {novel_id}
    for _kind, rows in _grouped_rows(plan):
        package.update(ids(rows))
    groups = {
        "volumes": ids(plan.volumes),
        "chapters": ids(plan.chapters),
        "entities": ids(plan.entities),
        "proposals": ids(plan.proposals),
        "issues": ids(plan.issues),
        "tasks": ids(plan.tasks),
        "repairs": ids(plan.repairs),
    }
    groups["package"] = package
    groups["novel"] = {novel_id}
    return groups


def _link_problem(row: dict[str, object], indexes: dict[str, set[str]]) -> str | None:
    problems: list[str] = []

    def walk(value: object, key: str | None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                if not isinstance(child_key, str):
                    continue
                if child_key in _ID_LIST_KEYS and isinstance(child, list):
                    for entry in child:
                        if not isinstance(entry, str) or entry not in indexes["entities"]:
                            problems.append("出场人物或参与者不属于这本作品")
                    continue
                if child_key == "model_config_id" or child_key in _LABEL_ID_KEYS:
                    continue
                if child_key == "novel_id":
                    if child not in indexes["novel"]:
                        problems.append("引用了其他作品")
                    continue
                if child_key in {"volume_id"}:
                    if child is not None and child not in indexes["volumes"]:
                        problems.append("卷不属于这本作品")
                    continue
                if child_key in {
                    "chapter_id",
                    "source_chapter_id",
                    "introduced_chapter_id",
                    "payoff_chapter_id",
                }:
                    if child is not None and child not in indexes["chapters"]:
                        problems.append("章节不属于这本作品")
                    continue
                if child_key in {
                    "entity_id",
                    "from_entity_id",
                    "to_entity_id",
                    "location_entity_id",
                }:
                    if child is not None and child not in indexes["entities"]:
                        problems.append("设定不属于这本作品")
                    continue
                if (
                    child_key == "proposal_id"
                    and child is not None
                    and child not in indexes["proposals"]
                ):
                    problems.append("提案不属于这本作品")
                    continue
                if child_key == "issue_id" and child is not None and child not in indexes["issues"]:
                    problems.append("质量问题不属于这本作品")
                    continue
                if (
                    child_key == "ai_task_id"
                    and child is not None
                    and child not in indexes["tasks"]
                ):
                    problems.append("AI 任务不属于这本作品")
                    continue
                if (
                    child_key == "repair_candidate_id"
                    and child is not None
                    and child not in indexes["repairs"]
                ):
                    problems.append("修复候选不属于这本作品")
                    continue
                if (child_key == "ref_id" or child_key.endswith("_id")) and child_key != "id":
                    if isinstance(child, str) and child not in indexes["package"]:
                        problems.append("引用了作品包以外的编号")
                    elif child is not None and not isinstance(child, str):
                        problems.append("引用编号格式不对")
                    continue
                walk(child, child_key)
        elif isinstance(value, list) and key not in _ID_LIST_KEYS:
            for child in value:
                walk(child, None)

    walk(row, None)
    if not problems:
        return None
    return problems[0]


def _check_toc(archive: zipfile.ZipFile, toc: dict[str, object], plan: PackagePlan) -> None:
    if plan.novel is None:
        return
    expected = _live_dicts(plan.volumes, plan.chapters)
    raw_entries = toc.get("entries", [])
    if not isinstance(raw_entries, list):
        plan.invalid.bump("chapters")
        _reason(plan, "chapters", "正文目录无法读取")
        return
    found: list[str] = []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            plan.invalid.bump("chapters")
            _reason(plan, "chapters", "正文目录有无法读取的条目")
            return
        chapter_id = entry.get("chapter_id")
        markdown = entry.get("markdown")
        text = entry.get("text")
        if not isinstance(chapter_id, str):
            plan.invalid.bump("chapters")
            _reason(plan, "chapters", "正文目录缺少章节编号")
            return
        found.append(chapter_id)
        markdown_name = f"manuscript/{index:04d}.md"
        text_name = f"manuscript/{index:04d}.txt"
        if markdown != markdown_name or text != text_name:
            plan.invalid.bump("chapters")
            _reason(plan, "chapters", "正文文件顺序与目录不一致")
            return
        if not _member_text(archive, markdown_name) or not _member_text(archive, text_name):
            plan.invalid.bump("chapters")
            _reason(plan, "chapters", "正文文件缺失或无法读取")
            return
    expected_ids = [_text_of(chapter, "id") for chapter in expected]
    if found != expected_ids:
        plan.invalid.bump("chapters")
        _reason(plan, "chapters", "正文目录顺序与作品结构不一致")


def _member_text(archive: zipfile.ZipFile, name: str) -> bool:
    try:
        raw = archive.read(name)
    except KeyError:
        return False
    try:
        raw.decode("utf-8")
    except UnicodeError:
        return False
    return True


def _add_import_snapshots(plan: PackagePlan) -> None:
    covered = {(_text_of(row, "chapter_id"), _int_of(row, "revision")) for row in plan.versions}
    used = {_text_of(row, "id") for _kind, rows in _grouped_rows(plan) for row in rows}
    added = False
    for chapter in plan.chapters:
        key = (_text_of(chapter, "id"), _int_of(chapter, "revision"))
        if key in covered:
            continue
        snapshot_id = _fresh_local(used)
        plan.versions.append(
            {
                "id": snapshot_id,
                "chapter_id": key[0],
                "revision": key[1],
                "content_snapshot": chapter["content"],
                "change_source": "import",
                "change_note": "作品包导入时补上的当前正文快照。修订号没有增加。",
                "ai_task_id": None,
                "repair_candidate_id": None,
                "created_at": chapter["updated_at"],
            }
        )
        added = True
    if added:
        plan.warnings.append(
            "当前修订还没有快照的章节，导入时补了一条来源为导入的快照，修订号不变。"
        )


def _allocate_ids(session: Session, plan: PackagePlan) -> None:
    tables: dict[str, InstrumentedAttribute[str]] = {
        "novels": Novel.id,
        "volumes": Volume.id,
        "chapters": Chapter.id,
        "chapter_versions": ChapterVersion.id,
        "story_plans": StoryPlan.id,
        "story_arcs": StoryArc.id,
        "volume_outlines": VolumeOutline.id,
        "chapter_outlines": ChapterOutline.id,
        "scene_cards": SceneCard.id,
        "entities": StoryEntity.id,
        "entity_states": EntityState.id,
        "relations": EntityRelation.id,
        "events": StoryEvent.id,
        "summaries": ChapterSummary.id,
        "proposals": MemoryChangeProposal.id,
        "foreshadowing": Foreshadowing.id,
        "writing_goals": WritingGoal.id,
        "quality_issues": QualityIssue.id,
        "repair_candidates": QualityRepairCandidate.id,
        "ai_tasks": AiTask.id,
    }
    taken: set[str] = set()
    id_map: dict[str, str] = {}
    for kind, rows in _grouped_rows(plan):
        column = tables[kind]
        existing = _existing_ids(session, column, {_text_of(row, "id") for row in rows})
        for row in rows:
            source = _text_of(row, "id")
            if source in existing or source in taken:
                new_id = _fresh_db(session, column, taken)
                id_map[source] = new_id
                plan.conflict_map[source] = new_id
                plan.conflicts.bump(kind)
            else:
                id_map[source] = source
                taken.add(source)
    plan.conflict_map = id_map
    # Keep only real conflicts in the public map. The full map stays on the plan
    # via the same dict until remap; split them after copying.
    full_map = dict(id_map)
    plan.conflict_map = {source: target for source, target in full_map.items() if source != target}
    _remap_rows(plan, full_map)


def _remap_rows(plan: PackagePlan, id_map: dict[str, str]) -> None:
    if plan.novel is not None:
        _remap_row(plan.novel, id_map)
    for _kind, rows in _grouped_rows(plan):
        for row in rows:
            _remap_row(row, id_map)
    if plan.conflicts.blocking() > 0:
        plan.warnings.append("包内编号与现有数据冲突，已生成新编号。现有作品不会被覆盖。")


def _remap_row(row: dict[str, object], id_map: dict[str, str]) -> None:
    remapped = _remap_value(row, id_map)
    if isinstance(remapped, dict):
        row.clear()
        row.update(remapped)
    row["model_config_id"] = None


def _remap_value(value: object, id_map: dict[str, str]) -> object:
    if isinstance(value, dict):
        rewritten: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            if key == "model_config_id":
                rewritten[key] = None
                continue
            if key in _LABEL_ID_KEYS:
                rewritten[key] = item
                continue
            if key in _ID_LIST_KEYS and isinstance(item, list):
                rewritten[key] = [
                    id_map.get(entry, entry) if isinstance(entry, str) else entry for entry in item
                ]
                continue
            if (
                item is not None
                and isinstance(item, str)
                and (key == "ref_id" or key == "id" or key.endswith("_id"))
            ):
                rewritten[key] = id_map.get(item, item)
                continue
            rewritten[key] = _remap_value(item, id_map)
        return rewritten
    if isinstance(value, list):
        return [_remap_value(item, id_map) for item in value]
    return value


def _fill_created(plan: PackagePlan) -> None:
    if not plan.can_import:
        for kind, rows in _grouped_rows(plan):
            if rows and kind != "novels":
                plan.created.bump(kind, len(rows))
        return
    for kind, rows in _grouped_rows(plan):
        plan.created.bump(kind, len(rows))


def _existing_ids(session: Session, column: InstrumentedAttribute[str], ids: set[str]) -> set[str]:
    if not ids:
        return set()
    found: set[str] = set()
    pending = list(ids)
    for start in range(0, len(pending), 400):
        chunk = pending[start : start + 400]
        found.update(session.scalars(select(column).where(column.in_(chunk))).all())
    return found


def _fresh_db(session: Session, column: InstrumentedAttribute[str], taken: set[str]) -> str:
    for _ in range(8):
        candidate = str(uuid.uuid4())
        if candidate in taken:
            continue
        if session.scalar(select(column).where(column == candidate)) is None:
            taken.add(candidate)
            return candidate
    raise PackageImportFailed("导入没有完成，没有留下半成品。")


def _fresh_local(used: set[str]) -> str:
    for _ in range(8):
        candidate = str(uuid.uuid4())
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise PackageInvalid("作品包无法分配编号。没有写入任何数据。")


def _write_back_singletons(plan: PackagePlan, kind: str, rows: list[dict[str, object]]) -> None:
    if kind == "story_plans":
        plan.story_plan = rows[0] if rows else None
    elif kind == "writing_goals":
        plan.writing_goal = rows[0] if rows else None
    elif kind == "novels":
        plan.novel = rows[0] if rows else None


def _live_order(volumes: list[Volume], chapters: list[Chapter]) -> list[Chapter]:
    ordered: list[Chapter] = []
    unassigned = sorted(
        (chapter for chapter in chapters if chapter.volume_id is None),
        key=lambda chapter: (chapter.sort_order, chapter.id),
    )
    ordered.extend(unassigned)
    for volume in sorted(volumes, key=lambda item: (item.sort_order, item.id)):
        grouped = sorted(
            (chapter for chapter in chapters if chapter.volume_id == volume.id),
            key=lambda chapter: (chapter.sort_order, chapter.id),
        )
        ordered.extend(grouped)
    return ordered


def _live_dicts(
    volumes: list[dict[str, object]], chapters: list[dict[str, object]]
) -> list[dict[str, object]]:
    live = [chapter for chapter in chapters if chapter.get("deleted_at") is None]
    ordered: list[dict[str, object]] = []
    unassigned = sorted(
        (chapter for chapter in live if chapter.get("volume_id") is None),
        key=lambda chapter: (_int_of(chapter, "sort_order"), _text_of(chapter, "id")),
    )
    ordered.extend(unassigned)
    volume_order = sorted(
        volumes,
        key=lambda item: (_int_of(item, "sort_order"), _text_of(item, "id")),
    )
    for volume in volume_order:
        volume_id = _text_of(volume, "id")
        grouped = sorted(
            (chapter for chapter in live if chapter.get("volume_id") == volume_id),
            key=lambda chapter: (_int_of(chapter, "sort_order"), _text_of(chapter, "id")),
        )
        ordered.extend(grouped)
    return ordered


def _ids_query[T](
    session: Session,
    model: type[T],
    column: InstrumentedAttribute[str],
    ids: list[str],
) -> list[T]:
    if not ids:
        return []
    found: list[T] = []
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        found.extend(session.scalars(select(model).where(column.in_(chunk))).all())
    return found


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _dump_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _as_document(content: object) -> dict[str, object]:
    if isinstance(content, dict):
        return cast(dict[str, object], copy.deepcopy(content))
    return {"type": "doc", "content": [{"type": "paragraph"}]}


def _novel_dict(row: Novel) -> dict[str, object]:
    return {
        "id": row.id,
        "title": row.title,
        "genre": row.genre,
        "synopsis": row.synopsis,
        "style_guide": row.style_guide,
        "status": row.status,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
        "deleted_at": None,
    }


def _volume_dict(row: Volume) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "title": row.title,
        "sort_order": row.sort_order,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _chapter_dict(row: Chapter) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "volume_id": row.volume_id,
        "title": row.title,
        "sort_order": row.sort_order,
        "content": _as_document(row.content),
        "content_format": row.content_format,
        "content_format_version": row.content_format_version,
        "word_count": row.word_count,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
        "deleted_at": _dump_dt(row.deleted_at),
    }


def _version_dict(row: ChapterVersion) -> dict[str, object]:
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "revision": row.revision,
        "content_snapshot": _as_document(row.content_snapshot),
        "content_format": row.content_format,
        "content_format_version": row.content_format_version,
        "change_source": row.change_source,
        "change_note": row.change_note,
        "ai_task_id": row.ai_task_id,
        "repair_candidate_id": row.repair_candidate_id,
        "created_at": _dump_dt(row.created_at),
    }


def _story_plan_dict(row: StoryPlan) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "logline": row.logline,
        "body": row.body,
        "ending_intent": row.ending_intent,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _story_arc_dict(row: StoryArc) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "arc_type": row.arc_type,
        "title": row.title,
        "summary": row.summary,
        "thread_visibility": row.thread_visibility,
        "sort_order": row.sort_order,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _volume_outline_dict(row: VolumeOutline) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "volume_id": row.volume_id,
        "goal": row.goal,
        "key_events": row.key_events,
        "start_state": row.start_state,
        "end_state": row.end_state,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _outline_dict(row: ChapterOutline) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "goal": row.goal,
        "must_advance": row.must_advance,
        "required_events": row.required_events,
        "allowed_reveals": row.allowed_reveals,
        "forbidden_reveals": row.forbidden_reveals,
        "target_words": row.target_words,
        "ending_hook": row.ending_hook,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _scene_dict(row: SceneCard) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "sort_order": row.sort_order,
        "goal": row.goal,
        "location_entity_id": row.location_entity_id,
        "character_entity_ids": list(row.character_entity_ids),
        "conflict": row.conflict,
        "turning_point": row.turning_point,
        "expected_outcome": row.expected_outcome,
        "must_convey": row.must_convey,
        "must_not_reveal": row.must_not_reveal,
        "status": row.status,
        "revision": row.revision,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _entity_dict(row: StoryEntity) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "entity_type": row.entity_type,
        "name": row.name,
        "aliases": list(row.aliases),
        "profile": copy.deepcopy(row.profile),
        "status": row.status,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
        "deleted_at": _dump_dt(row.deleted_at),
    }


def _state_dict(row: EntityState) -> dict[str, object]:
    return {
        "id": row.id,
        "entity_id": row.entity_id,
        "chapter_id": row.chapter_id,
        "source_revision": row.source_revision,
        "proposal_id": row.proposal_id,
        "state_data": copy.deepcopy(row.state_data),
        "evidence_quote": row.evidence_quote,
        "source_type": row.source_type,
        "valid_from_text": row.valid_from_text,
        "valid_until_text": row.valid_until_text,
        "created_at": _dump_dt(row.created_at),
    }


def _relation_dict(row: EntityRelation) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "from_entity_id": row.from_entity_id,
        "to_entity_id": row.to_entity_id,
        "relation_type": row.relation_type,
        "story_time_text": row.story_time_text,
        "storyline": row.storyline,
        "source_chapter_id": row.source_chapter_id,
        "source_revision": row.source_revision,
        "evidence_quote": row.evidence_quote,
        "status": row.status,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
        "deleted_at": _dump_dt(row.deleted_at),
    }


def _event_dict(row: StoryEvent) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "source_revision": row.source_revision,
        "proposal_id": row.proposal_id,
        "event_time_text": row.event_time_text,
        "description": row.description,
        "participants": list(row.participants),
        "evidence_quote": row.evidence_quote,
        "certainty": row.certainty,
        "created_at": _dump_dt(row.created_at),
        "deleted_at": _dump_dt(row.deleted_at),
    }


def _summary_dict(row: ChapterSummary) -> dict[str, object]:
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "summary": row.summary,
        "key_facts": list(row.key_facts),
        "source_revision": row.source_revision,
        "model_name": row.model_name,
        "status": row.status,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _proposal_dict(row: MemoryChangeProposal) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "source_chapter_id": row.source_chapter_id,
        "source_revision": row.source_revision,
        "proposal_type": row.proposal_type,
        "payload": copy.deepcopy(row.payload),
        "evidence_quote": row.evidence_quote,
        "certainty": row.certainty,
        "status": row.status,
        "review_note": row.review_note,
        "created_at": _dump_dt(row.created_at),
        "reviewed_at": _dump_dt(row.reviewed_at),
    }


def _foreshadowing_dict(row: Foreshadowing) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "introduced_chapter_id": row.introduced_chapter_id,
        "description": row.description,
        "status": row.status,
        "payoff_chapter_id": row.payoff_chapter_id,
        "evidence_quote": row.evidence_quote,
        "event_time_text": row.event_time_text,
        "character_discovered_text": row.character_discovered_text,
        "reader_revealed_text": row.reader_revealed_text,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _goal_dict(row: WritingGoal) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "target_words": row.target_words,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _issue_dict(row: QualityIssue) -> dict[str, object]:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "issue_type": row.issue_type,
        "severity": row.severity,
        "confidence": row.confidence,
        "status": row.status,
        "finding_class": row.finding_class,
        "manuscript_snippet": row.manuscript_snippet,
        "target_revision": row.target_revision,
        "location_note": row.location_note,
        "evidence_status": row.evidence_status,
        "evidence": copy.deepcopy(row.evidence),
        "related_refs": copy.deepcopy(row.related_refs),
        "rule_id": row.rule_id,
        "rule_version": row.rule_version,
        "analysis_version": row.analysis_version,
        "provider_mode": row.provider_mode,
        "suggested_action": row.suggested_action,
        "fingerprint": row.fingerprint,
        "fixed_revision": row.fixed_revision,
        "recheck_count": row.recheck_count,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _repair_dict(row: QualityRepairCandidate) -> dict[str, object]:
    return {
        "id": row.id,
        "issue_id": row.issue_id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "target_revision": row.target_revision,
        "apply_mode": row.apply_mode,
        "applicable": row.applicable,
        "original_snippet": row.original_snippet,
        "replacement_text": row.replacement_text,
        "rationale": row.rationale,
        "diff_preview": row.diff_preview,
        "provider_mode": row.provider_mode,
        "prompt_version": row.prompt_version,
        "status": row.status,
        "created_at": _dump_dt(row.created_at),
        "updated_at": _dump_dt(row.updated_at),
    }


def _task_dict(row: AiTask) -> dict[str, object]:
    snapshot = row.input_snapshot if isinstance(row.input_snapshot, dict) else {}
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "chapter_id": row.chapter_id,
        "task_type": row.task_type,
        "status": row.status,
        "model_config_id": row.model_config_id,
        "input_snapshot": copy.deepcopy(snapshot),
        "prompt_version": row.prompt_version,
        "output_text": row.output_text,
        "error_code": row.error_code,
        "error_message_safe": row.error_message_safe,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "resolution": row.resolution,
        "started_at": _dump_dt(row.started_at),
        "finished_at": _dump_dt(row.finished_at),
        "created_at": _dump_dt(row.created_at),
    }


def _model_dict(row: ModelConfig) -> dict[str, object]:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    capabilities = row.capabilities if isinstance(row.capabilities, dict) else {}
    return {
        "id": row.id,
        "display_name": row.display_name,
        "provider_type": row.provider_type,
        "base_url": row.base_url,
        "model_name": row.model_name,
        "is_enabled": row.is_enabled,
        "parameters": copy.deepcopy(parameters),
        "capabilities": copy.deepcopy(capabilities),
        "api_key_included": False,
        "reconfigure_required": True,
    }


def _download_name(title: str) -> str:
    cleaned = _FILENAME_UNSAFE.sub(" ", title).strip()
    cleaned = cleaned[:80] or "novel"
    return f"{cleaned}.novelpack.zip"


def _disposition(filename: str) -> str:
    from urllib.parse import quote

    encoded = quote(filename, safe="")
    return f"attachment; filename=\"novel.novelpack.zip\"; filename*=UTF-8''{encoded}"


def _reason(plan: PackagePlan, kind: str, message: str) -> None:
    if len(plan.invalid_reasons) >= 30:
        return
    plan.invalid_reasons.append(f"{_LABELS[kind]}：{message}")


def _refuse(reason: str) -> str:
    if "没有写入" in reason:
        return reason
    return f"{reason}。没有写入任何数据。"


def _record(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RowError("记录格式不对")
    return cast(dict[str, object], raw)


def _id(value: object, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise RowError("缺少编号")
        return None
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise RowError("编号格式不对")
    return value


def _text(
    value: object,
    *,
    max_len: int,
    required: bool,
    strip: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise RowError("缺少文本")
        return None
    if not isinstance(value, str):
        raise RowError("文本格式不对")
    text = value.strip() if strip else value
    if strip and text == "":
        raise RowError("文本不能为空")
    if len(text) > max_len:
        raise RowError("文本过长")
    return text


def _enum(value: object, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RowError("取值不在允许范围内")
    return value


def _optional_enum(value: object, allowed: set[str]) -> str | None:
    if value is None:
        return None
    return _enum(value, allowed)


def _number(value: object, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RowError("数字格式不对")
    if value < minimum or (maximum is not None and value > maximum):
        raise RowError("数字超出范围")
    return value


def _optional_number(value: object, *, minimum: int) -> int | None:
    if value is None:
        return None
    return _number(value, minimum=minimum)


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise RowError("布尔值格式不对")
    return value


def _when(value: object, *, required: bool) -> datetime | None:
    if value is None:
        if required:
            raise RowError("缺少时间")
        return None
    if not isinstance(value, str):
        raise RowError("时间格式不对")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RowError("时间格式不对") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _document(value: object) -> dict[str, object]:
    try:
        return validate_document(copy.deepcopy(value))
    except InvalidDocument as exc:
        raise RowError(exc.message) from exc


def _json_size(value: object, *, max_chars: int) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RowError("对象格式不对")
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) > max_chars:
        raise RowError("对象过大")
    return cast(dict[str, object], copy.deepcopy(value))


def _plain_list(value: object, *, max_len: int, max_items: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RowError("列表格式不对")
    if len(value) > max_items:
        raise RowError("列表过长")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) > max_len:
            raise RowError("列表项格式不对")
        items.append(item)
    return items


def _id_list(value: object) -> list[str]:
    items = _plain_list(value, max_len=36, max_items=50)
    for item in items:
        if _ID_RE.fullmatch(item) is None:
            raise RowError("编号格式不对")
    return items


def _dict_items(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RowError("列表格式不对")
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) > 500_000:
        raise RowError("列表过大")
    items: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RowError("列表项格式不对")
        items.append(cast(dict[str, object], copy.deepcopy(item)))
    return items


def _text_of(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise RowError("编号格式不对")
    return value


def _int_of(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RowError("数字格式不对")
    return value


def _s(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return value


def _opt_str(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return value


def _i(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return value


def _opt_int(row: dict[str, object], key: str) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    return _i(row, key)


def _b(row: dict[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return value


def _dt(row: dict[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return value


def _opt_dt(row: dict[str, object], key: str) -> datetime | None:
    value = row.get(key)
    if value is None:
        return None
    return _dt(row, key)


def _obj(row: dict[str, object], key: str) -> dict[str, object]:
    value = row.get(key)
    if not isinstance(value, dict):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return cast(dict[str, object], copy.deepcopy(value))


def _str_list_value(row: dict[str, object], key: str) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    return [item for item in value if isinstance(item, str)]


def _dict_list(row: dict[str, object], key: str) -> list[dict[str, object]]:
    value = row.get(key)
    if not isinstance(value, list):
        raise PackageImportFailed("导入没有完成，没有留下半成品。")
    items: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise PackageImportFailed("导入没有完成，没有留下半成品。")
        items.append(cast(dict[str, object], copy.deepcopy(item)))
    return items
