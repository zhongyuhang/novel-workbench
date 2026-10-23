"""Chronicle view and event planning on the existing story-event rows.

Planning writes ``chronicle_candidates`` only. Accept is what inserts a
``story_events`` row. Manual create and update write that row directly.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.gateway import enabled_default, endpoint_from_config, latest_enabled
from app.ai.provider import ProviderError
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    ModelNotConfigured,
    NotFound,
    ProviderRequestFailed,
    TaskStateError,
)
from app.core.redaction import redact_text
from app.models.catalog import Chapter, Novel
from app.models.chronicle import ChronicleCandidate
from app.models.memory import StoryEntity, StoryEvent
from app.models.planning import StoryArc
from app.models.quality import Foreshadowing
from app.repositories import catalog as catalog_repo
from app.schemas.chronicle import (
    CandidateStatus,
    ChronicleAccept,
    ChronicleCandidateResponse,
    ChronicleDecisionResponse,
    ChronicleEventPatch,
    ChronicleEventWrite,
    ChroniclePlanRequest,
    ChroniclePlanResponse,
    ChronicleView,
    ProviderMode,
)
from app.schemas.memory import Certainty, StoryEventResponse
from app.services.memory import (
    _event_response,
    _load_config,
    _public_provider_error,
    generate_analysis_text,
)
from app.services.quality_rules import parse_story_time

logger = logging.getLogger("app.chronicle")

PROMPT_VERSION = "chronicle_plan_v1"
_OPEN = frozenset({"pending", "deferred"})
_SCALE_RANK = {"date": 0, "day": 1, "chapter": 2}
_CERTAINTIES = frozenset({"confirmed", "inferred", "uncertain"})


def list_chronicle(session: Session, novel_id: str) -> ChronicleView:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(StoryEvent).where(
            StoryEvent.novel_id == novel_id,
            StoryEvent.deleted_at.is_(None),
        )
    ).all()
    ordered = sorted(rows, key=_sort_key)
    return ChronicleView(
        novel_id=novel_id,
        events=[_event_response(session, row) for row in ordered],
    )


def create_event(
    session: Session,
    novel_id: str,
    payload: ChronicleEventWrite,
) -> StoryEventResponse:
    _require_novel(session, novel_id)
    before = _manuscript_snapshot(session, novel_id)
    row = _new_event(
        session,
        novel_id,
        title=payload.title,
        description=payload.description,
        event_time_text=payload.event_time_text,
        sort_order=payload.sort_order,
        participants=payload.participants,
        participant_entity_ids=payload.participant_entity_ids,
        chapter_id=payload.chapter_id,
        story_arc_id=payload.story_arc_id,
        foreshadowing_id=payload.foreshadowing_id,
        evidence_quote=payload.evidence_quote or "",
        certainty=payload.certainty,
    )
    session.add(row)
    _commit_keeping_manuscript(session, novel_id, before)
    session.refresh(row)
    logger.info("chronicle event created")
    return _event_response(session, row)


def update_event(
    session: Session,
    event_id: str,
    payload: ChronicleEventPatch,
) -> StoryEventResponse:
    row = _require_event(session, event_id)
    before = _manuscript_snapshot(session, row.novel_id)
    fields = payload.model_fields_set
    if "title" in fields:
        row.title = payload.title
    if "description" in fields:
        if payload.description is None:
            raise InvalidReference("请填写事件。")
        row.description = payload.description
    if "event_time_text" in fields:
        row.event_time_text = payload.event_time_text
    if "sort_order" in fields:
        row.sort_order = payload.sort_order
    if "evidence_quote" in fields:
        row.evidence_quote = payload.evidence_quote or ""
    if "certainty" in fields and payload.certainty is not None:
        row.certainty = payload.certainty
    if "chapter_id" in fields:
        chapter = _optional_chapter(session, row.novel_id, payload.chapter_id)
        row.chapter_id = chapter.id if chapter is not None else None
        if chapter is not None and row.source_revision is None:
            row.source_revision = chapter.revision
    if "story_arc_id" in fields:
        _optional_arc(session, row.novel_id, payload.story_arc_id)
        row.story_arc_id = payload.story_arc_id
    if "foreshadowing_id" in fields:
        _optional_hook(session, row.novel_id, payload.foreshadowing_id)
        row.foreshadowing_id = payload.foreshadowing_id
    if "participants" in fields or "participant_entity_ids" in fields:
        names = (
            payload.participants
            if "participants" in fields and payload.participants is not None
            else _names(row.participants)
        )
        explicit = (
            payload.participant_entity_ids
            if "participant_entity_ids" in fields and payload.participant_entity_ids is not None
            else []
        )
        if "participant_entity_ids" not in fields:
            explicit = []
        row.participants = names
        row.participant_entity_ids = _resolve_participants(
            session,
            row.novel_id,
            names,
            explicit,
        )
    _commit_keeping_manuscript(session, row.novel_id, before)
    session.refresh(row)
    logger.info("chronicle event updated")
    return _event_response(session, row)


def delete_event(session: Session, event_id: str) -> None:
    row = _require_event(session, event_id)
    before = _manuscript_snapshot(session, row.novel_id)
    row.deleted_at = _now()
    _commit_keeping_manuscript(session, row.novel_id, before)
    logger.info("chronicle event deleted")


def list_candidates(
    session: Session,
    novel_id: str,
    status: str | None,
) -> list[ChronicleCandidateResponse]:
    _require_novel(session, novel_id)
    stmt = select(ChronicleCandidate).where(ChronicleCandidate.novel_id == novel_id)
    if status is not None:
        stmt = stmt.where(ChronicleCandidate.status == status)
    stmt = stmt.order_by(ChronicleCandidate.created_at.desc(), ChronicleCandidate.id.asc())
    return [_candidate_response(row) for row in session.scalars(stmt)]


def plan_events(
    session: Session,
    novel_id: str,
    payload: ChroniclePlanRequest,
) -> ChroniclePlanResponse:
    novel = _require_novel(session, novel_id)
    mode, model_name, config_id = _provider_mode(session, payload)
    before = _manuscript_snapshot(session, novel_id)
    event_count = _event_count(session, novel_id)
    drafts = _drafts(session, novel, payload.hint, mode, config_id)
    now = _now()
    rows: list[ChronicleCandidate] = []
    for draft in drafts:
        row = ChronicleCandidate(
            id=_new_id(),
            novel_id=novel_id,
            status="pending",
            title=draft["title"],
            description=draft["description"],
            event_time_text=draft["event_time_text"],
            sort_order=None,
            participants=draft["participants"],
            participant_entity_ids=[],
            chapter_id=None,
            story_arc_id=None,
            foreshadowing_id=None,
            evidence_quote="",
            certainty="inferred",
            hint=payload.hint,
            model_config_id=config_id,
            provider_mode=mode,
            model_name=model_name,
            prompt_version=PROMPT_VERSION,
            review_note=None,
            applied=None,
            created_at=now,
            reviewed_at=None,
        )
        session.add(row)
        rows.append(row)
    _commit_keeping_manuscript(session, novel_id, before)
    if _event_count(session, novel_id) != event_count:
        logger.error("chronicle planning changed formal events")
    for row in rows:
        session.refresh(row)
    logger.info("chronicle candidates planned")
    note = "模拟规划，尚未写入正式事件。" if mode == "mock" else "模型规划尚未写入正式事件。"
    return ChroniclePlanResponse(
        novel_id=novel_id,
        provider_mode="mock" if mode == "mock" else "openai_compatible",
        simulated=mode == "mock",
        model_config_id=config_id,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        candidates=[_candidate_response(row) for row in rows],
        note=note,
    )


def accept_candidate(
    session: Session,
    candidate_id: str,
    payload: ChronicleAccept,
) -> ChronicleDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status not in _OPEN:
        raise TaskStateError("这份候选已经处理过。")
    before = _manuscript_snapshot(session, candidate.novel_id)
    written = payload.event
    fields = written.model_fields_set if written is not None else set()
    title = written.title if written is not None and "title" in fields else candidate.title
    description = (
        written.description
        if written is not None and "description" in fields
        else candidate.description
    )
    event_time = (
        written.event_time_text
        if written is not None and "event_time_text" in fields
        else candidate.event_time_text
    )
    sort_order = (
        written.sort_order
        if written is not None and "sort_order" in fields
        else candidate.sort_order
    )
    names = (
        written.participants
        if written is not None and "participants" in fields
        else _names(candidate.participants)
    )
    explicit = (
        written.participant_entity_ids
        if written is not None and "participant_entity_ids" in fields
        else _ids(candidate.participant_entity_ids)
    )
    chapter_id = (
        written.chapter_id
        if written is not None and "chapter_id" in fields
        else candidate.chapter_id
    )
    arc_id = (
        written.story_arc_id
        if written is not None and "story_arc_id" in fields
        else candidate.story_arc_id
    )
    hook_id = (
        written.foreshadowing_id
        if written is not None and "foreshadowing_id" in fields
        else candidate.foreshadowing_id
    )
    evidence = (
        written.evidence_quote
        if written is not None and "evidence_quote" in fields
        else candidate.evidence_quote
    )
    certainty = (
        written.certainty
        if written is not None and "certainty" in fields
        else _certainty(candidate.certainty)
    )
    event = _new_event(
        session,
        candidate.novel_id,
        title=title,
        description=description,
        event_time_text=event_time,
        sort_order=sort_order,
        participants=names,
        participant_entity_ids=explicit,
        chapter_id=chapter_id,
        story_arc_id=arc_id,
        foreshadowing_id=hook_id,
        evidence_quote=evidence or "",
        certainty=certainty,
    )
    session.add(event)
    now = _now()
    candidate.title = title
    candidate.description = description
    candidate.event_time_text = event_time
    candidate.sort_order = sort_order
    candidate.participants = names
    candidate.participant_entity_ids = list(event.participant_entity_ids or [])
    candidate.chapter_id = event.chapter_id
    candidate.story_arc_id = event.story_arc_id
    candidate.foreshadowing_id = event.foreshadowing_id
    candidate.evidence_quote = event.evidence_quote
    candidate.certainty = event.certainty
    candidate.status = "accepted"
    candidate.review_note = payload.review_note
    candidate.applied = {"story_event_id": event.id}
    candidate.reviewed_at = now
    _commit_keeping_manuscript(session, candidate.novel_id, before)
    session.refresh(candidate)
    session.refresh(event)
    logger.info("chronicle candidate accepted")
    return ChronicleDecisionResponse(
        candidate=_candidate_response(candidate),
        event=_event_response(session, event),
        formal_material_changed=True,
    )


def reject_candidate(session: Session, candidate_id: str) -> ChronicleDecisionResponse:
    return _close(session, candidate_id, "rejected")


def defer_candidate(session: Session, candidate_id: str) -> ChronicleDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status != "pending":
        raise TaskStateError("只有还没处理的候选可以延后。")
    return _close(session, candidate_id, "deferred")


def _close(session: Session, candidate_id: str, status: str) -> ChronicleDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status not in _OPEN:
        raise TaskStateError("这份候选已经处理过。")
    before = _manuscript_snapshot(session, candidate.novel_id)
    event_count = _event_count(session, candidate.novel_id)
    candidate.status = status
    candidate.reviewed_at = _now()
    _commit_keeping_manuscript(session, candidate.novel_id, before)
    if _event_count(session, candidate.novel_id) != event_count:
        logger.error("chronicle review changed formal events")
    session.refresh(candidate)
    logger.info("chronicle candidate updated")
    return ChronicleDecisionResponse(
        candidate=_candidate_response(candidate),
        event=None,
        formal_material_changed=False,
    )


def _new_event(
    session: Session,
    novel_id: str,
    *,
    title: str | None,
    description: str,
    event_time_text: str | None,
    sort_order: int | None,
    participants: list[str],
    participant_entity_ids: list[str],
    chapter_id: str | None,
    story_arc_id: str | None,
    foreshadowing_id: str | None,
    evidence_quote: str,
    certainty: str,
) -> StoryEvent:
    chapter = _optional_chapter(session, novel_id, chapter_id)
    _optional_arc(session, novel_id, story_arc_id)
    _optional_hook(session, novel_id, foreshadowing_id)
    linked = _resolve_participants(session, novel_id, participants, participant_entity_ids)
    return StoryEvent(
        id=_new_id(),
        novel_id=novel_id,
        chapter_id=chapter.id if chapter is not None else None,
        source_revision=chapter.revision if chapter is not None else None,
        proposal_id=None,
        title=title,
        event_time_text=event_time_text,
        sort_order=sort_order,
        description=description,
        participants=participants,
        participant_entity_ids=linked,
        story_arc_id=story_arc_id,
        foreshadowing_id=foreshadowing_id,
        evidence_quote=evidence_quote,
        certainty=certainty if certainty in _CERTAINTIES else "uncertain",
        created_at=_now(),
        deleted_at=None,
    )


def _drafts(
    session: Session,
    novel: Novel,
    hint: str | None,
    mode: str,
    config_id: str | None,
) -> list[dict[str, object]]:
    if mode == "mock":
        return _mock_drafts(session, novel.id, hint)
    if config_id is None:
        raise ModelNotConfigured()
    config = _load_config(session, config_id)
    prompt = redact_text(_prompt(session, novel, hint))
    try:
        raw = generate_analysis_text(endpoint=endpoint_from_config(config), prompt=prompt)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    try:
        return _drafts_from_text(raw)
    except ValueError as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的事件规划。正式事件没有改动。",
            502,
        ) from exc


def _mock_drafts(session: Session, novel_id: str, hint: str | None) -> list[dict[str, object]]:
    characters = _characters(session, novel_id)
    name = characters[0].name if characters else "人物"
    chapters = session.scalars(
        select(Chapter)
        .where(Chapter.novel_id == novel_id, Chapter.deleted_at.is_(None))
        .order_by(Chapter.sort_order.asc(), Chapter.id.asc())
    ).all()
    chapter_title = chapters[0].title if chapters else "尚未分章"
    note = hint or "顺着已有材料排一件还没写进正文的事"
    participants = [name] if characters else []
    return [
        {
            "title": "规划：事情开始",
            "description": f"「{name}」遇上第一件要记进编年史的事。{note}",
            "event_time_text": "第1天",
            "participants": participants,
        },
        {
            "title": "规划：事情往后",
            "description": (f"在「{chapter_title}」之后，留下一个还没写进正文的结果。"),
            "event_time_text": "第3天",
            "participants": participants,
        },
    ]


def _prompt(session: Session, novel: Novel, hint: str | None) -> str:
    characters = [row.name for row in _characters(session, novel.id)]
    arcs = session.scalars(
        select(StoryArc).where(StoryArc.novel_id == novel.id).order_by(StoryArc.sort_order.asc())
    ).all()
    chapters = session.scalars(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.deleted_at.is_(None))
        .order_by(Chapter.sort_order.asc())
    ).all()
    events = session.scalars(
        select(StoryEvent).where(
            StoryEvent.novel_id == novel.id,
            StoryEvent.deleted_at.is_(None),
        )
    ).all()
    existing = [
        f"{row.event_time_text or '时间未填写'} {row.description[:80]}"
        for row in sorted(events, key=_sort_key)[:12]
    ]
    return (
        "只返回一个 JSON 对象，不要写 Markdown。"
        "不要把它当成已经写入的正式事件。\n"
        '{"events":[{"title":"","description":"","event_time_text":"","participants":[""]}]}\n'
        "最多 6 条。description 必填。"
        "event_time_text 用「第N天」、公历 YYYY-MM-DD 或「第N章」，"
        "不知道就留空。participants 只写人物名字。不要发明编号。\n"
        f"作品：{novel.title}\n"
        f"作者的规划说明：{hint or '（没有额外说明）'}\n"
        f"已有人物：{'、'.join(characters) or '（还没有人物）'}\n"
        f"已有故事线：{'、'.join(row.title for row in arcs) or '（还没有故事线）'}\n"
        f"已有章节：{'、'.join(row.title for row in chapters) or '（还没有章节）'}\n"
        f"已有事件：{'；'.join(existing) or '（还没有事件）'}"
    )


def _drafts_from_text(raw: str) -> list[dict[str, object]]:
    parsed = _load_object(raw)
    rows = parsed.get("events")
    if not isinstance(rows, list):
        raise ValueError("missing events")
    drafts: list[dict[str, object]] = []
    for item in rows[:6]:
        if not isinstance(item, dict):
            continue
        description = item.get("description")
        if not isinstance(description, str) or description.strip() == "":
            continue
        title = item.get("title")
        when = item.get("event_time_text")
        names = item.get("participants")
        participants = (
            [part.strip() for part in names if isinstance(part, str) and part.strip()]
            if isinstance(names, list)
            else []
        )
        drafts.append(
            {
                "title": title.strip()[:200] if isinstance(title, str) and title.strip() else None,
                "description": description.strip()[:8000],
                "event_time_text": when.strip()[:200]
                if isinstance(when, str) and when.strip()
                else None,
                "participants": participants[:40],
            }
        )
    if not drafts:
        raise ValueError("no events")
    return drafts


def _load_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("not json")
    loaded = json.loads(text[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("not object")
    return loaded


def _provider_mode(
    session: Session,
    payload: ChroniclePlanRequest,
) -> tuple[str, str, str | None]:
    if payload.model_config_id:
        config = _load_config(session, payload.model_config_id)
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟生成不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return "mock", config.model_name, config.id
        return "openai_compatible", config.model_name, config.id
    if payload.use_mock:
        return "mock", "模拟模型", None
    default = enabled_default(session)
    if default is not None:
        if default.provider_type == "mock":
            return "mock", default.model_name, default.id
        return "openai_compatible", default.model_name, default.id
    found = latest_enabled(session, "openai_compatible")
    if found is None:
        raise ModelNotConfigured()
    return "openai_compatible", found.model_name, found.id


def _sort_key(row: StoryEvent) -> tuple[object, ...]:
    parsed = parse_story_time(row.event_time_text)
    if parsed is None:
        manual = row.sort_order if row.sort_order is not None else 10**9
        return (1, 0, 0, manual, row.created_at, row.id)
    scale, value = parsed
    tie = row.sort_order if row.sort_order is not None else 0
    return (0, _SCALE_RANK.get(scale, 9), value, tie, row.created_at, row.id)


def _resolve_participants(
    session: Session,
    novel_id: str,
    names: list[str],
    explicit: list[str],
) -> list[str]:
    linked = _require_characters(session, novel_id, explicit)
    by_name: dict[str, list[str]] = {}
    for row in _characters(session, novel_id):
        by_name.setdefault(row.name, []).append(row.id)
    for name in names:
        matches = by_name.get(name, [])
        if len(matches) == 1 and matches[0] not in linked:
            linked.append(matches[0])
    return linked


def _require_characters(session: Session, novel_id: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    found = {row.id: row for row in _characters(session, novel_id)}
    linked: list[str] = []
    for entity_id in ids:
        row = found.get(entity_id)
        if row is None:
            other = session.get(StoryEntity, entity_id)
            if other is None or other.deleted_at is not None or other.novel_id != novel_id:
                raise InvalidReference("参与人物必须是这本作品里的人物。")
            if other.entity_type != "character":
                raise InvalidReference("事件的人物关联只能指向人物。")
            raise InvalidReference("参与人物必须是这本作品里的人物。")
        if entity_id not in linked:
            linked.append(entity_id)
    return linked


def _characters(session: Session, novel_id: str) -> list[StoryEntity]:
    return list(
        session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.deleted_at.is_(None),
                StoryEntity.entity_type == "character",
            )
        ).all()
    )


def _optional_chapter(session: Session, novel_id: str, chapter_id: str | None) -> Chapter | None:
    if chapter_id is None:
        return None
    chapter = session.get(Chapter, chapter_id)
    if chapter is None or chapter.deleted_at is not None or chapter.novel_id != novel_id:
        raise InvalidReference("章节不属于这本作品。")
    return chapter


def _optional_arc(session: Session, novel_id: str, arc_id: str | None) -> None:
    if arc_id is None:
        return
    arc = session.get(StoryArc, arc_id)
    if arc is None or arc.novel_id != novel_id:
        raise InvalidReference("故事线不属于这本作品。")


def _optional_hook(session: Session, novel_id: str, hook_id: str | None) -> None:
    if hook_id is None:
        return
    hook = session.get(Foreshadowing, hook_id)
    if hook is None or hook.novel_id != novel_id:
        raise InvalidReference("伏笔不属于这本作品。")


def _candidate_response(row: ChronicleCandidate) -> ChronicleCandidateResponse:
    status = cast(
        CandidateStatus,
        row.status if row.status in {"pending", "accepted", "rejected", "deferred"} else "pending",
    )
    mode = cast(
        ProviderMode,
        row.provider_mode if row.provider_mode in {"mock", "openai_compatible"} else "mock",
    )
    return ChronicleCandidateResponse(
        id=row.id,
        novel_id=row.novel_id,
        status=status,
        title=row.title,
        description=row.description,
        event_time_text=row.event_time_text,
        sort_order=row.sort_order,
        participants=_names(row.participants),
        participant_entity_ids=_ids(row.participant_entity_ids),
        chapter_id=row.chapter_id,
        story_arc_id=row.story_arc_id,
        foreshadowing_id=row.foreshadowing_id,
        evidence_quote=row.evidence_quote,
        certainty=_certainty(row.certainty),
        hint=row.hint,
        model_config_id=row.model_config_id,
        provider_mode=mode,
        model_name=row.model_name,
        prompt_version=row.prompt_version,
        applied=row.applied if isinstance(row.applied, dict) else None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in names:
            names.append(item.strip())
    return names


def _ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in found:
            found.append(item.strip())
    return found


def _certainty(value: str) -> Certainty:
    if value in {"confirmed", "inferred", "uncertain"}:
        return cast(Certainty, value)
    return "uncertain"


def _event_count(session: Session, novel_id: str) -> int:
    return len(session.scalars(select(StoryEvent.id).where(StoryEvent.novel_id == novel_id)).all())


def _require_novel(session: Session, novel_id: str) -> Novel:
    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    return novel


def _require_event(session: Session, event_id: str) -> StoryEvent:
    row = session.get(StoryEvent, event_id)
    if (
        row is None
        or row.deleted_at is not None
        or catalog_repo.get_novel(session, row.novel_id) is None
    ):
        raise NotFound("事件不存在。")
    return row


def _require_candidate(session: Session, candidate_id: str) -> ChronicleCandidate:
    row = session.get(ChronicleCandidate, candidate_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("这份候选不存在。")
    return row


def _manuscript_snapshot(session: Session, novel_id: str) -> tuple[tuple[object, ...], ...]:
    rows = session.scalars(select(Chapter).where(Chapter.novel_id == novel_id)).all()
    return tuple(
        (
            row.id,
            row.revision,
            row.word_count,
            json.dumps(row.content, ensure_ascii=False, sort_keys=True),
        )
        for row in rows
    )


def _commit_keeping_manuscript(
    session: Session,
    novel_id: str,
    before: tuple[tuple[object, ...], ...],
) -> None:
    if _manuscript_snapshot(session, novel_id) != before:
        session.rollback()
        raise InvalidReference("编年史不能修改正文。")
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise InvalidReference("这份事件没有写上。") from exc


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
