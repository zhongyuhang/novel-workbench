"""Memory use cases.

Chapter analysis inserts proposals only. Accept is the only path that writes formal
memory, and it does not change the manuscript.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

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
    SecretStorageUnavailable,
    TaskStateError,
)
from app.core.secrets import SecretStorageError, decrypt_api_key
from app.models.ai import ModelConfig
from app.models.catalog import Chapter
from app.models.memory import (
    ChapterSummary,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard
from app.repositories import catalog as catalog_repo
from app.schemas.memory import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChapterSummaryResponse,
    EntityCreate,
    EntityResponse,
    EntityStateResponse,
    EntityUpdate,
    ProposalResponse,
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


def analyze_chapter(
    session: Session,
    chapter_id: str,
    payload: AnalyzeRequest,
) -> AnalyzeResponse:
    chapter = _require_chapter(session, chapter_id)
    if chapter.revision != payload.revision:
        raise RevisionConflict()
    text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
    mode, model_name = _resolve_analyzer(session, payload)
    if text.strip() == "":
        drafts: list[ProposalDraft] = []
        message = "这一章还没有可分析的正文。正式设定没有改动。"
    else:
        drafts = _drafts_for_mode(mode, model_name, chapter, text, session, payload)
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
    payload: AnalyzeRequest,
) -> list[ProposalDraft]:
    del model_name
    if mode == "mock":
        return extract_from_chapter(text)
    config = _require_config(session, payload.model_config_id)
    endpoint = _endpoint_from_config(config)
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
    payload["before"] = {
        "entity_type": entity.entity_type,
        "name": entity.name,
        "aliases": _aliases(entity.aliases),
        "profile": _profile(entity.profile),
        "status": entity.status,
    }
    if "name" in payload and payload.get("name") is not None:
        name = _required_text(payload.get("name"), "设定名称无效。")
        _ensure_unique_name(session, proposal.novel_id, name, exclude_id=entity.id)
        entity.name = name
    entity_type = (
        _choice(payload.get("entity_type"), _ENTITY_TYPES) if "entity_type" in payload else None
    )
    if entity_type is not None:
        entity.entity_type = entity_type
    if "aliases" in payload:
        entity.aliases = _aliases(payload.get("aliases"))
    if "profile" in payload:
        entity.profile = _profile(payload.get("profile"))
    status = _choice(payload.get("status"), _ENTITY_STATUSES) if "status" in payload else None
    if status is not None:
        entity.status = status
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


def _resolve_analyzer(session: Session, payload: AnalyzeRequest) -> tuple[str, str]:
    if payload.model_config_id:
        config = _load_config(session, payload.model_config_id)
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟分析不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return "mock", "模拟分析"
        return "openai_compatible", config.model_name
    if payload.use_mock:
        return "mock", "模拟分析"
    found = _default_external_config(session)
    if found is None:
        raise ModelNotConfigured()
    return "openai_compatible", found.model_name


def _require_config(session: Session, config_id: str | None) -> ModelConfig:
    config = _load_config(session, config_id) if config_id else _default_external_config(session)
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


def _default_external_config(session: Session) -> ModelConfig | None:
    return session.scalars(
        select(ModelConfig)
        .where(
            ModelConfig.is_enabled.is_(True),
            ModelConfig.provider_type == "openai_compatible",
        )
        .order_by(ModelConfig.updated_at.desc(), ModelConfig.id.asc())
    ).first()


def _endpoint_from_config(config: ModelConfig) -> ModelEndpoint:
    parameters = config.parameters if isinstance(config.parameters, dict) else {}
    capabilities = config.capabilities if isinstance(config.capabilities, dict) else {}
    if not config.secret_ref:
        raise ModelConfigInvalid("这个模型还没有可用的 API Key。")
    try:
        api_key = decrypt_api_key(str(config.secret_ref))
    except SecretStorageError as exc:
        raise SecretStorageUnavailable() from exc
    return ModelEndpoint(
        base_url=str(config.base_url),
        model_name=str(config.model_name),
        api_key=api_key,
        timeout_seconds=_float(parameters.get("timeout_seconds"), 60),
        supports_streaming=capabilities.get("supports_streaming") is not False,
        provider_type="openai_compatible",
        max_retries=_int(parameters.get("max_retries"), 2),
        temperature=_optional_float(parameters.get("temperature")),
        max_output_tokens=_optional_int(parameters.get("max_output_tokens")) or 1200,
        parameters=parameters,
    )


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


def _entity_in_novel(session: Session, entity_id: str, novel_id: str) -> StoryEntity:
    entity = session.get(StoryEntity, entity_id)
    if entity is None or entity.deleted_at is not None or entity.novel_id != novel_id:
        raise InvalidReference("提案指向的设定不存在，或不属于这本作品。")
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


def _float(value: object, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


def _int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
