"""Memory use cases.

Chapter analysis inserts proposals only. Accept is the only path that writes formal
memory, and it does not change the manuscript.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.ai.gateway import enabled_default, endpoint_from_config, latest_enabled
from app.ai.prompts import ANALYZE_PROMPT_VERSION, build_analyze_prompt
from app.ai.provider import GenerationRequest, ModelEndpoint, ProviderError
from app.ai.registry import get_provider
from app.core.content import document_to_text
from app.core.errors import (
    DuplicateEntity,
    InvalidReference,
    ModelConfigInvalid,
    ModelNotConfigured,
    NotFound,
    ProviderRequestFailed,
    RevisionConflict,
    TaskStateError,
)
from app.models.ai import ModelConfig
from app.models.catalog import Chapter
from app.models.memory import (
    ChapterSummary,
    EntityRelation,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard, VolumeOutline
from app.repositories import catalog as catalog_repo
from app.schemas.memory import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChapterSummaryResponse,
    EntityCreate,
    EntityResponse,
    EntityStateCreate,
    EntityStateResponse,
    EntityStateUpdate,
    EntityUpdate,
    ProposalResponse,
    RelationResponse,
    RelationUpdate,
    RelationWrite,
    StoryEventResponse,
)
from app.services.memory_extract import (
    ProposalDraft,
    extract_from_chapter,
    parse_analysis_output,
)

logger = logging.getLogger("app.memory")

_ENTITY_TYPES = {"character", "location", "organization", "item", "rule", "other"}
_ENTITY_STATUSES = {"active", "inactive", "unknown"}
_RELATION_STATUSES = {"active", "ended", "unknown"}
_ENTITY_FIELDS = ("entity_type", "name", "aliases", "profile", "status")
_FIELD_LABELS = {
    "entity_type": "类型",
    "name": "名称",
    "aliases": "别名",
    "profile": "档案",
    "status": "状态",
}
_CERTAINTIES = {"confirmed", "inferred", "uncertain"}
_SOURCE_TYPES = {"manual", "ai_proposal", "import"}


def list_entities(session: Session, novel_id: str) -> list[EntityResponse]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(StoryEntity)
        .where(StoryEntity.novel_id == novel_id, StoryEntity.deleted_at.is_(None))
        .order_by(StoryEntity.created_at.asc(), StoryEntity.id.asc())
    ).all()
    return [_entity_response(session, row) for row in rows]


def create_entity(session: Session, novel_id: str, payload: EntityCreate) -> EntityResponse:
    _require_novel(session, novel_id)
    _ensure_unique_name(session, novel_id, payload.name, exclude_id=None)
    now = _now()
    row = StoryEntity(
        id=_new_id(),
        novel_id=novel_id,
        entity_type=payload.entity_type,
        name=payload.name,
        aliases=list(payload.aliases),
        profile=_profile(payload.profile),
        status=payload.status,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("story entity created")
    return _entity_response(session, row)


def update_entity(session: Session, entity_id: str, payload: EntityUpdate) -> EntityResponse:
    row = _require_entity(session, entity_id)
    if payload.name is not None:
        _ensure_unique_name(session, row.novel_id, payload.name, exclude_id=row.id)
        row.name = payload.name
    if payload.entity_type is not None:
        row.entity_type = payload.entity_type
    if payload.aliases is not None:
        row.aliases = list(payload.aliases)
    if payload.profile is not None:
        row.profile = _profile(payload.profile)
    if payload.status is not None:
        row.status = payload.status
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("story entity updated")
    return _entity_response(session, row)


def list_proposals(
    session: Session,
    novel_id: str,
    status: str | None,
) -> list[ProposalResponse]:
    _require_novel(session, novel_id)
    stmt = select(MemoryChangeProposal).where(MemoryChangeProposal.novel_id == novel_id)
    if status is not None:
        stmt = stmt.where(MemoryChangeProposal.status == status)
    stmt = stmt.order_by(MemoryChangeProposal.created_at.desc(), MemoryChangeProposal.id.asc())
    return [_proposal_response(session, row) for row in session.scalars(stmt)]


def list_chapter_summaries(session: Session, novel_id: str) -> list[ChapterSummaryResponse]:
    _require_novel(session, novel_id)
    stmt = (
        select(ChapterSummary, Chapter)
        .join(Chapter, Chapter.id == ChapterSummary.chapter_id)
        .where(Chapter.novel_id == novel_id, Chapter.deleted_at.is_(None))
        .order_by(ChapterSummary.created_at.desc(), ChapterSummary.id.asc())
    )
    responses: list[ChapterSummaryResponse] = []
    for summary, chapter in session.execute(stmt).all():
        responses.append(_summary_response(summary, chapter))
    return responses


def list_events(session: Session, novel_id: str) -> list[StoryEventResponse]:
    _require_novel(session, novel_id)
    stmt = (
        select(StoryEvent)
        .where(StoryEvent.novel_id == novel_id, StoryEvent.deleted_at.is_(None))
        .order_by(StoryEvent.created_at.desc(), StoryEvent.id.asc())
    )
    return [_event_response(session, row) for row in session.scalars(stmt)]


def create_entity_state(
    session: Session,
    entity_id: str,
    payload: EntityStateCreate,
) -> EntityStateResponse:
    entity = _require_entity(session, entity_id)
    chapter = _require_chapter(session, payload.chapter_id)
    if chapter.novel_id != entity.novel_id:
        raise InvalidReference("来源章节不属于这本作品。")
    state = EntityState(
        id=_new_id(),
        entity_id=entity.id,
        chapter_id=chapter.id,
        source_revision=chapter.revision,
        proposal_id=None,
        state_data=_profile(payload.state_data),
        evidence_quote=payload.evidence_quote,
        source_type="manual",
        valid_from_text=payload.valid_from_text,
        valid_until_text=payload.valid_until_text,
        created_at=_now(),
    )
    session.add(state)
    session.commit()
    session.refresh(state)
    logger.info("entity state created")
    return _state_response(session, state)


def update_entity_state(
    session: Session,
    state_id: str,
    payload: EntityStateUpdate,
) -> EntityStateResponse:
    state = _require_state(session, state_id)
    fields = payload.model_fields_set
    if "state_data" in fields and payload.state_data is not None:
        state.state_data = _profile(payload.state_data)
    if "evidence_quote" in fields:
        state.evidence_quote = payload.evidence_quote
    if "valid_from_text" in fields:
        state.valid_from_text = payload.valid_from_text
    if "valid_until_text" in fields:
        state.valid_until_text = payload.valid_until_text
    session.commit()
    session.refresh(state)
    logger.info("entity state updated")
    return _state_response(session, state)


def delete_entity_state(session: Session, state_id: str) -> None:
    state = _require_state(session, state_id)
    session.delete(state)
    session.commit()
    logger.info("entity state deleted")


def list_relations(
    session: Session,
    novel_id: str,
    *,
    entity_id: str | None,
    chapter_id: str | None,
    status: str | None,
    storyline: str | None,
) -> list[RelationResponse]:
    _require_novel(session, novel_id)
    if entity_id is not None:
        _entity_in_novel(session, entity_id, novel_id)
    if chapter_id is not None:
        chapter = _require_chapter(session, chapter_id)
        if chapter.novel_id != novel_id:
            raise InvalidReference("来源章节不属于这本作品。")
    stmt = select(EntityRelation).where(
        EntityRelation.novel_id == novel_id,
        EntityRelation.deleted_at.is_(None),
    )
    if entity_id is not None:
        stmt = stmt.where(
            or_(
                EntityRelation.from_entity_id == entity_id,
                EntityRelation.to_entity_id == entity_id,
            )
        )
    if chapter_id is not None:
        stmt = stmt.where(EntityRelation.source_chapter_id == chapter_id)
    if status is not None:
        stmt = stmt.where(EntityRelation.status == status)
    stmt = stmt.order_by(EntityRelation.created_at.asc(), EntityRelation.id.asc())
    rows = list(session.scalars(stmt))
    needle = _optional_text(storyline)
    if needle is not None:
        folded = needle.casefold()
        rows = [
            row
            for row in rows
            if isinstance(row.storyline, str) and folded in row.storyline.casefold()
        ]
    return [_relation_response(session, row) for row in rows]


def create_relation(
    session: Session,
    novel_id: str,
    payload: RelationWrite,
) -> RelationResponse:
    _require_novel(session, novel_id)
    chapter_id, revision = _relation_source(
        session,
        novel_id,
        payload.source_chapter_id,
        payload.source_revision,
    )
    _relation_ends(session, novel_id, payload.from_entity_id, payload.to_entity_id)
    now = _now()
    row = EntityRelation(
        id=_new_id(),
        novel_id=novel_id,
        from_entity_id=payload.from_entity_id,
        to_entity_id=payload.to_entity_id,
        relation_type=payload.relation_type,
        story_time_text=payload.story_time_text,
        storyline=payload.storyline,
        source_chapter_id=chapter_id,
        source_revision=revision,
        evidence_quote=payload.evidence_quote,
        status=payload.status,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("entity relation created")
    return _relation_response(session, row)


def update_relation(
    session: Session,
    relation_id: str,
    payload: RelationUpdate,
) -> RelationResponse:
    row = _require_relation(session, relation_id)
    fields = payload.model_fields_set
    from_id = payload.from_entity_id if "from_entity_id" in fields else row.from_entity_id
    to_id = payload.to_entity_id if "to_entity_id" in fields else row.to_entity_id
    if from_id is None or to_id is None:
        raise InvalidReference("关系的两端不能为空。")
    _relation_ends(session, row.novel_id, from_id, to_id)
    row.from_entity_id = from_id
    row.to_entity_id = to_id
    if "relation_type" in fields and payload.relation_type is not None:
        row.relation_type = payload.relation_type
    if "story_time_text" in fields:
        row.story_time_text = payload.story_time_text
    if "storyline" in fields:
        row.storyline = payload.storyline
    if "evidence_quote" in fields:
        row.evidence_quote = payload.evidence_quote
    if "status" in fields and payload.status is not None:
        row.status = payload.status
    if "source_chapter_id" in fields or "source_revision" in fields:
        chapter_id = (
            payload.source_chapter_id if "source_chapter_id" in fields else row.source_chapter_id
        )
        if "source_revision" in fields:
            revision = payload.source_revision
        elif chapter_id is None:
            revision = None
        else:
            revision = row.source_revision
        row.source_chapter_id, row.source_revision = _relation_source(
            session,
            row.novel_id,
            chapter_id,
            revision,
        )
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("entity relation updated")
    return _relation_response(session, row)


def delete_relation(session: Session, relation_id: str) -> None:
    row = _require_relation(session, relation_id)
    now = _now()
    row.deleted_at = now
    row.updated_at = now
    session.commit()
    logger.info("entity relation deleted")


def analyze_chapter(
    session: Session,
    chapter_id: str,
    payload: AnalyzeRequest,
) -> AnalyzeResponse:
    chapter = _require_chapter(session, chapter_id)
    if chapter.revision != payload.revision:
        raise RevisionConflict()
    text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
    mode, model_name, used_config_id = _resolve_analyzer(session, payload)
    if text.strip() == "":
        drafts: list[ProposalDraft] = []
        message = "这一章还没有可分析的正文。正式设定没有改动。"
    else:
        drafts = _drafts_for_mode(
            mode,
            model_name,
            chapter,
            text,
            session,
            used_config_id,
        )
        if mode == "mock":
            message = "模拟分析已生成提案。正式设定和正文都没有自动改动。"
        elif drafts:
            message = "已生成提案。正式设定和正文都没有自动改动。"
        else:
            message = "没有产生可审核的提案。正式设定没有改动。"
    now = _now()
    rows: list[MemoryChangeProposal] = []
    for draft in drafts:
        body = _copy_payload(draft.payload)
        body["evidence_in_source"] = draft.evidence_in_source
        body["model_name"] = model_name
        body["model_config_id"] = used_config_id
        row = MemoryChangeProposal(
            id=_new_id(),
            novel_id=chapter.novel_id,
            source_chapter_id=chapter.id,
            source_revision=chapter.revision,
            proposal_type=draft.proposal_type,
            payload=body,
            evidence_quote=draft.evidence_quote,
            certainty=draft.certainty,
            status="pending",
            review_note=None,
            created_at=now,
            reviewed_at=None,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    logger.info("chapter analysis stored proposals", extra={"count": len(rows)})
    return AnalyzeResponse(
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
        source_revision=chapter.revision,
        status="completed",
        provider_mode="mock" if mode == "mock" else "openai_compatible",
        model_name=model_name,
        model_config_id=used_config_id,
        prompt_version=ANALYZE_PROMPT_VERSION,
        proposal_count=len(rows),
        proposals=[_proposal_response(session, row) for row in rows],
        message=message,
    )


def accept_proposal(
    session: Session,
    proposal_id: str,
    review_note: str | None,
) -> ProposalResponse:
    proposal = _require_proposal(session, proposal_id)
    if proposal.status not in {"pending", "stale"}:
        raise TaskStateError("只有待审核或已过期的提案才能接受。")
    chapter = _require_chapter(session, proposal.source_chapter_id)
    if chapter.novel_id != proposal.novel_id:
        raise InvalidReference("提案和来源章节不属于同一本作品。")
    payload = _copy_payload(proposal.payload)
    applied = _apply(session, proposal, payload)
    payload["applied"] = applied
    proposal.payload = payload
    proposal.status = "accepted"
    proposal.review_note = review_note
    proposal.reviewed_at = _now()
    session.commit()
    session.refresh(proposal)
    logger.info("memory proposal accepted")
    return _proposal_response(session, proposal)


def reject_proposal(
    session: Session,
    proposal_id: str,
    review_note: str | None,
) -> ProposalResponse:
    proposal = _require_proposal(session, proposal_id)
    if proposal.status not in {"pending", "stale"}:
        raise TaskStateError("只有待审核或已过期的提案才能拒绝。")
    proposal.status = "rejected"
    proposal.review_note = review_note
    proposal.reviewed_at = _now()
    session.commit()
    session.refresh(proposal)
    logger.info("memory proposal rejected")
    return _proposal_response(session, proposal)


def revert_proposal(
    session: Session,
    proposal_id: str,
    review_note: str | None,
) -> ProposalResponse:
    proposal = _require_proposal(session, proposal_id)
    if proposal.status != "accepted":
        raise TaskStateError("只有已接受的提案才能撤回。")
    payload = _copy_payload(proposal.payload)
    applied = payload.get("applied")
    if not isinstance(applied, dict):
        raise TaskStateError("这份提案没有可撤回的记录。")
    _revert_applied(session, proposal, payload, applied)
    proposal.payload = payload
    proposal.status = "reverted"
    proposal.review_note = review_note
    proposal.reviewed_at = _now()
    session.commit()
    session.refresh(proposal)
    logger.info("memory proposal reverted")
    return _proposal_response(session, proposal)


def mark_chapter_memory_stale(session: Session, chapter_id: str, revision: int) -> None:
    """Mark summaries, pending proposals, and confirmed chapter plans as stale.

    Confirmed chapter outlines and scene cards describe the previous manuscript.
    A confirmed outline for that chapter's volume is marked stale the same way.
    Their text is left unchanged. Draft and archived rows stay as they are.
    The novel-level story plan is not expired by one chapter revision.
    """

    now = _now()
    session.execute(
        update(ChapterSummary)
        .where(
            ChapterSummary.chapter_id == chapter_id,
            ChapterSummary.status == "current",
            ChapterSummary.source_revision != revision,
        )
        .values(status="stale", updated_at=now)
    )
    session.execute(
        update(MemoryChangeProposal)
        .where(
            MemoryChangeProposal.source_chapter_id == chapter_id,
            MemoryChangeProposal.status == "pending",
            MemoryChangeProposal.source_revision != revision,
        )
        .values(status="stale")
    )
    session.execute(
        update(ChapterOutline)
        .where(
            ChapterOutline.chapter_id == chapter_id,
            ChapterOutline.status == "confirmed",
        )
        .values(status="stale", revision=ChapterOutline.revision + 1, updated_at=now)
    )
    session.execute(
        update(SceneCard)
        .where(
            SceneCard.chapter_id == chapter_id,
            SceneCard.status == "confirmed",
        )
        .values(status="stale", revision=SceneCard.revision + 1, updated_at=now)
    )
    chapter = session.get(Chapter, chapter_id)
    if chapter is not None and chapter.volume_id is not None:
        session.execute(
            update(VolumeOutline)
            .where(
                VolumeOutline.novel_id == chapter.novel_id,
                VolumeOutline.volume_id == chapter.volume_id,
                VolumeOutline.status == "confirmed",
            )
            .values(status="stale", revision=VolumeOutline.revision + 1, updated_at=now)
        )


def generate_analysis_text(*, endpoint: ModelEndpoint, prompt: str) -> str:
    provider = get_provider(endpoint)
    provider.validate_config(endpoint)
    result = provider.generate(
        GenerationRequest(
            endpoint=endpoint,
            prompt=prompt,
            max_output_tokens=endpoint.max_output_tokens,
        )
    )
    return result.text


def _drafts_for_mode(
    mode: str,
    model_name: str,
    chapter: Chapter,
    text: str,
    session: Session,
    config_id: str | None,
) -> list[ProposalDraft]:
    del model_name
    if mode == "mock":
        return extract_from_chapter(text)
    config = _require_config(session, config_id)
    endpoint = endpoint_from_config(config)
    prompt = build_analyze_prompt(title=chapter.title, chapter_text=text)
    try:
        raw = generate_analysis_text(endpoint=endpoint, prompt=prompt)
        return parse_analysis_output(raw, text)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的记忆提案。正式设定没有改动。",
            502,
        ) from exc


def _apply(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    kind = proposal.proposal_type
    if kind == "entity_create":
        return _apply_entity_create(session, proposal, payload)
    if kind == "entity_update":
        return _apply_entity_update(session, proposal, payload)
    if kind == "entity_state":
        return _apply_entity_state(session, proposal, payload)
    if kind == "story_event":
        return _apply_event(session, proposal, payload)
    if kind == "chapter_summary":
        return _apply_summary(session, proposal, payload)
    raise InvalidReference("不支持的提案类型。")


def _apply_entity_create(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    name = _required_text(payload.get("name"), "提案缺少设定名称。")
    entity_type = _choice(payload.get("entity_type"), _ENTITY_TYPES)
    if entity_type is None:
        raise InvalidReference("提案里的设定类型无效。")
    _ensure_unique_name(session, proposal.novel_id, name, exclude_id=None)
    status = _choice(payload.get("status"), _ENTITY_STATUSES) or "active"
    if proposal.certainty != "confirmed":
        status = "unknown"
    now = _now()
    entity = StoryEntity(
        id=_new_id(),
        novel_id=proposal.novel_id,
        entity_type=entity_type,
        name=name,
        aliases=_aliases(payload.get("aliases")),
        profile=_profile(payload.get("profile")),
        status=status,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(entity)
    session.flush()
    state = _add_state(
        session,
        entity_id=entity.id,
        proposal=proposal,
        state_data={"change": "create", "certainty": proposal.certainty},
        now=now,
    )
    return _applied(entity.id, True, state.id, None, None)


def _apply_entity_update(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    entity = _entity_in_novel(
        session,
        _required_text(payload.get("target_entity_id"), "提案缺少要更新的设定。"),
        proposal.novel_id,
    )
    before = _entity_snapshot(entity)
    payload["before"] = before
    changes: list[dict[str, object]] = []
    if "name" in payload and payload.get("name") is not None:
        name = _required_text(payload.get("name"), "设定名称无效。")
        if not _json_equal(before["name"], name):
            _ensure_unique_name(session, proposal.novel_id, name, exclude_id=entity.id)
            entity.name = name
            changes.append({"field": "name", "before": before["name"], "after": name})
    entity_type = (
        _choice(payload.get("entity_type"), _ENTITY_TYPES) if "entity_type" in payload else None
    )
    if entity_type is not None and not _json_equal(before["entity_type"], entity_type):
        entity.entity_type = entity_type
        changes.append(
            {"field": "entity_type", "before": before["entity_type"], "after": entity_type}
        )
    if "aliases" in payload:
        aliases = _aliases(payload.get("aliases"))
        if not _json_equal(before["aliases"], aliases):
            entity.aliases = aliases
            changes.append({"field": "aliases", "before": before["aliases"], "after": aliases})
    if "profile" in payload:
        profile = _profile(payload.get("profile"))
        if not _json_equal(before["profile"], profile):
            entity.profile = profile
            changes.append({"field": "profile", "before": before["profile"], "after": profile})
    status = _choice(payload.get("status"), _ENTITY_STATUSES) if "status" in payload else None
    if status is not None and not _json_equal(before["status"], status):
        entity.status = status
        changes.append({"field": "status", "before": before["status"], "after": status})
    payload["field_changes"] = changes
    if changes:
        entity.updated_at = _now()
    state = _add_state(
        session,
        entity_id=entity.id,
        proposal=proposal,
        state_data={"change": "update", "certainty": proposal.certainty},
        now=_now(),
    )
    return _applied(entity.id, False, state.id, None, None)


def _apply_entity_state(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    entity = _entity_in_novel(
        session,
        _required_text(payload.get("target_entity_id"), "提案缺少要更新的设定。"),
        proposal.novel_id,
    )
    state = _add_state(
        session,
        entity_id=entity.id,
        proposal=proposal,
        state_data=_profile(payload.get("state_data")),
        now=_now(),
        valid_from_text=_optional_text(payload.get("valid_from_text")),
        valid_until_text=_optional_text(payload.get("valid_until_text")),
    )
    return _applied(entity.id, False, state.id, None, None)


def _apply_event(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    description = _required_text(payload.get("description"), "提案缺少事件描述。")
    certainty = proposal.certainty if proposal.certainty in _CERTAINTIES else "uncertain"
    event = StoryEvent(
        id=_new_id(),
        novel_id=proposal.novel_id,
        chapter_id=proposal.source_chapter_id,
        source_revision=proposal.source_revision,
        proposal_id=proposal.id,
        event_time_text=_optional_text(payload.get("event_time_text")),
        description=description,
        participants=_aliases(payload.get("participants")),
        evidence_quote=proposal.evidence_quote,
        certainty=certainty,
        created_at=_now(),
        deleted_at=None,
    )
    session.add(event)
    return _applied(None, False, None, event.id, None)


def _apply_summary(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
) -> dict[str, object]:
    summary_text = _required_text(payload.get("summary"), "提案缺少章节摘要。")
    model_name = payload.get("model_name")
    now = _now()
    summary = ChapterSummary(
        id=_new_id(),
        chapter_id=proposal.source_chapter_id,
        summary=summary_text,
        key_facts=_aliases(payload.get("key_facts")),
        source_revision=proposal.source_revision,
        model_name=model_name if isinstance(model_name, str) else None,
        status="current",
        created_at=now,
        updated_at=now,
    )
    session.add(summary)
    return _applied(None, False, None, None, summary.id)


def _add_state(
    session: Session,
    *,
    entity_id: str,
    proposal: MemoryChangeProposal,
    state_data: dict[str, object],
    now: datetime,
    valid_from_text: str | None = None,
    valid_until_text: str | None = None,
) -> EntityState:
    state = EntityState(
        id=_new_id(),
        entity_id=entity_id,
        chapter_id=proposal.source_chapter_id,
        source_revision=proposal.source_revision,
        proposal_id=proposal.id,
        state_data=state_data,
        evidence_quote=proposal.evidence_quote or None,
        source_type="ai_proposal",
        valid_from_text=valid_from_text,
        valid_until_text=valid_until_text,
        created_at=now,
    )
    session.add(state)
    return state


def _revert_applied(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
    applied: dict[str, Any],
) -> None:
    now = _now()
    if proposal.proposal_type == "entity_update":
        _revert_entity_fields(session, proposal, payload, applied, now)
    else:
        entity_id = applied.get("entity_id")
        if isinstance(entity_id, str):
            entity = session.get(StoryEntity, entity_id)
            if entity is not None and entity.novel_id == proposal.novel_id:
                if applied.get("created_entity") is True:
                    entity.deleted_at = now
                    entity.updated_at = now
                else:
                    before = payload.get("before")
                    if isinstance(before, dict):
                        _restore_entity(entity, before, now)
    state_id = applied.get("state_id")
    if isinstance(state_id, str):
        state = session.get(EntityState, state_id)
        if state is not None:
            session.delete(state)
    event_id = applied.get("event_id")
    if isinstance(event_id, str):
        event = session.get(StoryEvent, event_id)
        if event is not None and event.novel_id == proposal.novel_id:
            event.deleted_at = now
    summary_id = applied.get("summary_id")
    if isinstance(summary_id, str):
        summary = session.get(ChapterSummary, summary_id)
        if summary is not None and summary.chapter_id == proposal.source_chapter_id:
            summary.status = "rejected"
            summary.updated_at = now


def _restore_entity(entity: StoryEntity, before: dict[str, Any], now: datetime) -> None:
    """Whole-snapshot restore. Not used for entity_update."""

    entity_type = _choice(before.get("entity_type"), _ENTITY_TYPES)
    status = _choice(before.get("status"), _ENTITY_STATUSES)
    name = before.get("name")
    if entity_type is not None:
        entity.entity_type = entity_type
    if isinstance(name, str) and name.strip():
        entity.name = name.strip()
    entity.aliases = _aliases(before.get("aliases"))
    entity.profile = _profile(before.get("profile"))
    if status is not None:
        entity.status = status
    entity.updated_at = now


def _revert_entity_fields(
    session: Session,
    proposal: MemoryChangeProposal,
    payload: dict[str, Any],
    applied: dict[str, Any],
    now: datetime,
) -> None:
    """Roll back only the fields this acceptance changed.

    A field edited after acceptance blocks the whole revert. Older proposals
    that only stored a full ``before`` snapshot are refused, so a later manual
    edit cannot be overwritten.
    """

    changes = _parse_field_changes(payload)
    entity_id = applied.get("entity_id")
    entity = session.get(StoryEntity, entity_id) if isinstance(entity_id, str) else None
    if entity is None or entity.deleted_at is not None or entity.novel_id != proposal.novel_id:
        raise TaskStateError("要撤回的设定已经不在，或已删除。撤回已取消，正式设定没有改动。")
    conflicts = [
        _FIELD_LABELS[item["field"]]
        for item in changes
        if not _json_equal(_current_field(entity, item["field"]), item["after"])
    ]
    if conflicts:
        names = "、".join(conflicts)
        raise TaskStateError(f"这些字段在接受之后又被改过：{names}。撤回已取消，正式设定没有改动。")
    for item in changes:
        if item["field"] != "name":
            continue
        before_name = item["before"]
        if not isinstance(before_name, str) or before_name.strip() == "":
            raise TaskStateError("字段级变更记录里的名称无效。撤回已取消，正式设定没有改动。")
        try:
            _ensure_unique_name(
                session,
                entity.novel_id,
                before_name.strip(),
                exclude_id=entity.id,
            )
        except DuplicateEntity as exc:
            raise TaskStateError(
                "撤回名称会和现有设定重名。撤回已取消，正式设定没有改动。"
            ) from exc
    if not changes:
        return
    for item in changes:
        _assign_entity_field(entity, item["field"], item["before"])
    entity.updated_at = now


def _parse_field_changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "field_changes" not in payload or not isinstance(payload.get("field_changes"), list):
        raise TaskStateError(
            "这份设定更新没有字段级变更记录，不能自动撤回，以免盖掉后来的修改。正式设定没有改动。"
        )
    raw = payload["field_changes"]
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TaskStateError("字段级变更记录不完整。撤回已取消，正式设定没有改动。")
        field = item.get("field")
        if not isinstance(field, str) or field not in _ENTITY_FIELDS:
            raise TaskStateError("字段级变更记录不完整。撤回已取消，正式设定没有改动。")
        if "before" not in item or "after" not in item:
            raise TaskStateError("字段级变更记录不完整。撤回已取消，正式设定没有改动。")
        parsed.append({"field": field, "before": item.get("before"), "after": item.get("after")})
    return parsed


def _entity_snapshot(entity: StoryEntity) -> dict[str, object]:
    return {
        "entity_type": entity.entity_type,
        "name": entity.name,
        "aliases": _aliases(entity.aliases),
        "profile": _profile(entity.profile),
        "status": entity.status,
    }


def _current_field(entity: StoryEntity, field: str) -> object:
    if field == "aliases":
        return _aliases(entity.aliases)
    if field == "profile":
        return _profile(entity.profile)
    return getattr(entity, field)


def _assign_entity_field(entity: StoryEntity, field: str, value: object) -> None:
    if field == "name":
        entity.name = _required_text(value, "字段级变更记录里的名称无效。")
        return
    if field == "entity_type":
        chosen = _choice(value, _ENTITY_TYPES)
        if chosen is None:
            raise TaskStateError("字段级变更记录里的类型无效。撤回已取消，正式设定没有改动。")
        entity.entity_type = chosen
        return
    if field == "status":
        chosen = _choice(value, _ENTITY_STATUSES)
        if chosen is None:
            raise TaskStateError("字段级变更记录里的状态无效。撤回已取消，正式设定没有改动。")
        entity.status = chosen
        return
    if field == "aliases":
        entity.aliases = _aliases(value)
        return
    if field == "profile":
        entity.profile = _profile(value)
        return
    raise TaskStateError("字段级变更记录不完整。撤回已取消，正式设定没有改动。")


def _json_equal(left: object, right: object) -> bool:
    return _canon(left) == _canon(right)


def _canon(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _canon(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canon(item) for item in value]
    return value


def _resolve_analyzer(session: Session, payload: AnalyzeRequest) -> tuple[str, str, str | None]:
    if payload.model_config_id:
        config = _load_config(session, payload.model_config_id)
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟分析不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return "mock", "模拟分析", config.id
        return "openai_compatible", config.model_name, config.id
    if payload.use_mock:
        return "mock", "模拟分析", None
    default = enabled_default(session)
    if default is not None:
        if default.provider_type == "mock":
            return "mock", "模拟分析", default.id
        return "openai_compatible", default.model_name, default.id
    found = latest_enabled(session, "openai_compatible")
    if found is None:
        raise ModelNotConfigured()
    return "openai_compatible", found.model_name, found.id


def _require_config(session: Session, config_id: str | None) -> ModelConfig:
    config: ModelConfig | None
    if config_id:
        config = _load_config(session, config_id)
    else:
        default = enabled_default(session)
        if default is not None and default.provider_type == "openai_compatible":
            config = default
        else:
            config = latest_enabled(session, "openai_compatible")
    if config is None or config.provider_type != "openai_compatible":
        raise ModelNotConfigured()
    return config


def _load_config(session: Session, config_id: str) -> ModelConfig:
    config = session.get(ModelConfig, config_id)
    if config is None:
        raise NotFound("模型配置不存在。")
    if not config.is_enabled:
        raise ModelConfigInvalid("这个模型配置已停用。")
    return config


def _entity_response(session: Session, row: StoryEntity) -> EntityResponse:
    states = session.scalars(
        select(EntityState)
        .where(EntityState.entity_id == row.id)
        .order_by(EntityState.created_at.desc(), EntityState.id.desc())
    ).all()
    return EntityResponse(
        id=row.id,
        novel_id=row.novel_id,
        entity_type=_entity_type_literal(row.entity_type),
        name=row.name,
        aliases=_aliases(row.aliases),
        profile=_profile(row.profile),
        status=_status_literal(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        states=[_state_response(session, state) for state in states],
    )


def _state_response(session: Session, state: EntityState) -> EntityStateResponse:
    chapter = session.get(Chapter, state.chapter_id)
    source_type = state.source_type if state.source_type in _SOURCE_TYPES else "manual"
    return EntityStateResponse(
        id=state.id,
        entity_id=state.entity_id,
        chapter_id=state.chapter_id,
        chapter_title=chapter.title if chapter is not None else "未知章节",
        source_revision=state.source_revision,
        state_data=_profile(state.state_data),
        evidence_quote=state.evidence_quote,
        source_type=cast("Any", source_type),
        valid_from_text=state.valid_from_text,
        valid_until_text=state.valid_until_text,
        created_at=state.created_at,
    )


def _proposal_response(session: Session, row: MemoryChangeProposal) -> ProposalResponse:
    chapter = session.get(Chapter, row.source_chapter_id)
    payload = _copy_payload(row.payload)
    applied = payload.get("applied") if isinstance(payload.get("applied"), dict) else {}
    applied_map = applied if isinstance(applied, dict) else {}
    evidence_flag = payload.get("evidence_in_source")
    return ProposalResponse(
        id=row.id,
        novel_id=row.novel_id,
        source_chapter_id=row.source_chapter_id,
        source_chapter_title=chapter.title if chapter is not None else "未知章节",
        source_revision=row.source_revision,
        proposal_type=_proposal_type_literal(row.proposal_type),
        payload=payload,
        evidence_quote=row.evidence_quote,
        certainty=_certainty_literal(row.certainty),
        evidence_in_source=evidence_flag is True
        or (
            row.evidence_quote != ""
            and evidence_flag is not False
            and row.evidence_quote in _chapter_text(chapter)
        ),
        status=_proposal_status_literal(row.status),
        review_note=row.review_note,
        applied_entity_id=_optional_text(applied_map.get("entity_id")),
        applied_state_id=_optional_text(applied_map.get("state_id")),
        applied_event_id=_optional_text(applied_map.get("event_id")),
        applied_summary_id=_optional_text(applied_map.get("summary_id")),
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _summary_response(summary: ChapterSummary, chapter: Chapter) -> ChapterSummaryResponse:
    status = summary.status if summary.status in {"current", "stale", "rejected"} else "stale"
    return ChapterSummaryResponse(
        id=summary.id,
        novel_id=chapter.novel_id,
        chapter_id=summary.chapter_id,
        chapter_title=chapter.title,
        summary=summary.summary,
        key_facts=_aliases(summary.key_facts),
        source_revision=summary.source_revision,
        chapter_revision=chapter.revision,
        model_name=summary.model_name,
        status=cast("Any", status),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _event_response(session: Session, row: StoryEvent) -> StoryEventResponse:
    chapter = session.get(Chapter, row.chapter_id)
    return StoryEventResponse(
        id=row.id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        chapter_title=chapter.title if chapter is not None else "未知章节",
        source_revision=row.source_revision,
        chapter_revision=chapter.revision if chapter is not None else 0,
        event_time_text=row.event_time_text,
        description=row.description,
        participants=_aliases(row.participants),
        evidence_quote=row.evidence_quote,
        certainty=_certainty_literal(row.certainty),
        created_at=row.created_at,
    )


def _ensure_unique_name(
    session: Session,
    novel_id: str,
    name: str,
    exclude_id: str | None,
) -> None:
    target = _normalize_name(name)
    rows = session.scalars(
        select(StoryEntity).where(
            StoryEntity.novel_id == novel_id,
            StoryEntity.deleted_at.is_(None),
        )
    )
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if _normalize_name(row.name) == target:
            raise DuplicateEntity()


def _entity_in_novel(
    session: Session,
    entity_id: str,
    novel_id: str,
    *,
    message: str = "提案指向的设定不存在，或不属于这本作品。",
) -> StoryEntity:
    entity = session.get(StoryEntity, entity_id)
    if entity is None or entity.deleted_at is not None or entity.novel_id != novel_id:
        raise InvalidReference(message)
    return entity


def _require_novel(session: Session, novel_id: str) -> None:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")


def _require_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None or catalog_repo.get_novel(session, chapter.novel_id) is None:
        raise NotFound("章节不存在。")
    return chapter


def _require_entity(session: Session, entity_id: str) -> StoryEntity:
    row = session.get(StoryEntity, entity_id)
    if row is None or row.deleted_at is not None:
        raise NotFound("设定不存在。")
    if catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("设定不存在。")
    return row


def _require_state(session: Session, state_id: str) -> EntityState:
    state = session.get(EntityState, state_id)
    if state is None:
        raise NotFound("动态状态不存在。")
    _require_entity(session, state.entity_id)
    return state


def _require_relation(session: Session, relation_id: str) -> EntityRelation:
    row = session.get(EntityRelation, relation_id)
    if row is None or row.deleted_at is not None:
        raise NotFound("人物关系不存在。")
    if catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("人物关系不存在。")
    return row


def _relation_ends(session: Session, novel_id: str, from_id: str, to_id: str) -> None:
    if from_id == to_id:
        raise InvalidReference("关系的两端不能是同一个设定。")
    missing = "关系的两端必须是这本作品里未删除的设定。"
    _entity_in_novel(session, from_id, novel_id, message=missing)
    _entity_in_novel(session, to_id, novel_id, message=missing)


def _relation_source(
    session: Session,
    novel_id: str,
    chapter_id: str | None,
    revision: int | None,
) -> tuple[str | None, int | None]:
    if chapter_id is None:
        if revision is not None:
            raise InvalidReference("填写来源修订时，需要同时填写来源章节。")
        return None, None
    chapter = _require_chapter(session, chapter_id)
    if chapter.novel_id != novel_id:
        raise InvalidReference("来源章节不属于这本作品。")
    if revision is None:
        return chapter.id, chapter.revision
    return chapter.id, revision


def _relation_response(session: Session, row: EntityRelation) -> RelationResponse:
    from_entity = session.get(StoryEntity, row.from_entity_id)
    to_entity = session.get(StoryEntity, row.to_entity_id)
    chapter = session.get(Chapter, row.source_chapter_id) if row.source_chapter_id else None
    status = row.status if row.status in _RELATION_STATUSES else "unknown"
    return RelationResponse(
        id=row.id,
        novel_id=row.novel_id,
        from_entity_id=row.from_entity_id,
        from_entity_name=from_entity.name if from_entity is not None else "已删除设定",
        to_entity_id=row.to_entity_id,
        to_entity_name=to_entity.name if to_entity is not None else "已删除设定",
        relation_type=row.relation_type,
        story_time_text=row.story_time_text,
        storyline=row.storyline,
        source_chapter_id=row.source_chapter_id,
        source_chapter_title=chapter.title if chapter is not None else None,
        source_revision=row.source_revision,
        evidence_quote=row.evidence_quote,
        status=cast("Any", status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_proposal(session: Session, proposal_id: str) -> MemoryChangeProposal:
    row = session.get(MemoryChangeProposal, proposal_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("提案不存在。")
    return row


def _applied(
    entity_id: str | None,
    created_entity: bool,
    state_id: str | None,
    event_id: str | None,
    summary_id: str | None,
) -> dict[str, object]:
    return {
        "entity_id": entity_id,
        "created_entity": created_entity,
        "state_id": state_id,
        "event_id": event_id,
        "summary_id": summary_id,
    }


def _public_provider_error(exc: ProviderError) -> ProviderRequestFailed:
    status = {
        "MODEL_TIMEOUT": 504,
        "MODEL_UNAVAILABLE": 503,
        "MODEL_RATE_LIMIT": 429,
        "MODEL_AUTH": 502,
        "MODEL_BAD_REQUEST": 422,
        "MODEL_BAD_RESPONSE": 502,
        "MODEL_CONFIG_INVALID": 422,
    }.get(exc.code, 502)
    return ProviderRequestFailed(exc.code, exc.safe_message, status)


def _chapter_text(chapter: Chapter | None) -> str:
    if chapter is None or not isinstance(chapter.content, dict):
        return ""
    return document_to_text(chapter.content)


def _copy_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    copied = json.loads(json.dumps(value, ensure_ascii=False))
    if not isinstance(copied, dict):
        return {}
    return cast(dict[str, Any], copied)


def _profile(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _aliases(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
    return cleaned[:20]


def _required_text(value: object, message: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise InvalidReference(message)
    return value.strip()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _choice(value: object, allowed: set[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().casefold().split())


def _entity_type_literal(value: str) -> Any:
    if value in _ENTITY_TYPES:
        return value
    return "other"


def _status_literal(value: str) -> Any:
    if value in _ENTITY_STATUSES:
        return value
    return "unknown"


def _certainty_literal(value: str) -> Any:
    if value in _CERTAINTIES:
        return value
    return "uncertain"


def _proposal_type_literal(value: str) -> Any:
    allowed = {
        "entity_create",
        "entity_update",
        "entity_state",
        "story_event",
        "chapter_summary",
    }
    if value in allowed:
        return value
    return "entity_create"


def _proposal_status_literal(value: str) -> Any:
    allowed = {"pending", "accepted", "rejected", "reverted", "stale"}
    if value in allowed:
        return value
    return "pending"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
