"""Story planning. Writes never touch chapter text, revision, or versions.

A plan counts as a binding constraint only while its status is confirmed.
Draft, stale, and archived rows stay stored so the author can see them.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.provider import ProviderError
from app.core.content import document_to_text
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    NotFound,
    ProviderRequestFailed,
    RevisionConflict,
)
from app.models.catalog import Chapter, Volume
from app.models.memory import StoryEntity
from app.models.planning import ChapterOutline, SceneCard, StoryArc, StoryPlan, VolumeOutline
from app.repositories import catalog as catalog_repo
from app.schemas.planning import (
    ChapterOutlineResponse,
    ChapterOutlineView,
    ChapterOutlineWrite,
    EntityRef,
    OutlineCandidateAccept,
    OutlineCandidateAcceptResult,
    OutlineCandidatePreview,
    OutlineCandidateRequest,
    OutlineCandidateScene,
    PlanningConfirm,
    PlanningStatus,
    SceneCardPatch,
    SceneCardResponse,
    SceneCardWrite,
    SceneReorder,
    StoryArcCreate,
    StoryArcPatch,
    StoryArcReorder,
    StoryArcResponse,
    StoryArcType,
    StoryPlanResponse,
    StoryPlanView,
    StoryPlanWrite,
    VolumeOutlineResponse,
    VolumeOutlineView,
    VolumeOutlineWrite,
)

logger = logging.getLogger("app.planning")

_STATUSES = {"draft", "confirmed", "stale", "archived"}
_ARC_TYPES = {"main", "subplot", "character", "other"}
_CONFLICT = "大纲已在其他操作中更新，请刷新后再保存。"


def planning_counts_as_fact(status: str) -> bool:
    """Unconfirmed plans are not mandatory facts."""

    return status == "confirmed"


def get_story_plan(session: Session, novel_id: str) -> StoryPlanView:
    _require_novel(session, novel_id)
    row = _story_plan(session, novel_id)
    return StoryPlanView(
        novel_id=novel_id,
        plan=_story_response(row) if row is not None else None,
    )


def save_story_plan(
    session: Session,
    novel_id: str,
    payload: StoryPlanWrite,
) -> StoryPlanResponse:
    _require_novel(session, novel_id)
    row = _story_plan(session, novel_id)
    now = _now()
    if row is None:
        if payload.expected_revision is not None:
            raise RevisionConflict(_CONFLICT)
        row = StoryPlan(
            id=_new_id(),
            novel_id=novel_id,
            logline=payload.logline,
            body=payload.body,
            ending_intent=payload.ending_intent,
            status=payload.status or "draft",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        _commit_plan(session)
        session.refresh(row)
        logger.info("story plan created")
        return _story_response(row)

    if payload.expected_revision != row.revision:
        raise RevisionConflict(_CONFLICT)
    changed = _assign_story_fields(row, payload)
    if changed:
        row.revision += 1
        row.updated_at = now
        _commit_plan(session)
        session.refresh(row)
        logger.info("story plan updated")
    return _story_response(row)


def confirm_story_plan(
    session: Session,
    novel_id: str,
    payload: PlanningConfirm,
) -> StoryPlanResponse:
    _require_novel(session, novel_id)
    row = _story_plan(session, novel_id)
    if row is None:
        raise NotFound("这本作品还没有大纲。")
    _mark_confirmed(session, row, payload.expected_revision)
    return _story_response(row)


def list_chapter_outlines(session: Session, novel_id: str) -> list[ChapterOutlineResponse]:
    _require_novel(session, novel_id)
    stmt = (
        select(ChapterOutline)
        .join(Chapter, Chapter.id == ChapterOutline.chapter_id)
        .where(
            ChapterOutline.novel_id == novel_id,
            Chapter.novel_id == novel_id,
            Chapter.deleted_at.is_(None),
        )
        .order_by(Chapter.sort_order.asc(), ChapterOutline.id.asc())
    )
    return [_outline_response(row) for row in session.scalars(stmt).all()]


def get_chapter_outline(session: Session, chapter_id: str) -> ChapterOutlineView:
    chapter = _require_chapter(session, chapter_id)
    row = _outline_for_chapter(session, chapter)
    return ChapterOutlineView(
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        outline=_outline_response(row) if row is not None else None,
    )


def save_chapter_outline(
    session: Session,
    chapter_id: str,
    payload: ChapterOutlineWrite,
) -> ChapterOutlineResponse:
    chapter = _require_chapter(session, chapter_id)
    row = _outline_for_chapter(session, chapter)
    now = _now()
    if row is None:
        if payload.expected_revision is not None:
            raise RevisionConflict(_CONFLICT)
        row = ChapterOutline(
            id=_new_id(),
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            goal=payload.goal,
            must_advance=payload.must_advance,
            required_events=payload.required_events,
            allowed_reveals=payload.allowed_reveals,
            forbidden_reveals=payload.forbidden_reveals,
            target_words=payload.target_words,
            ending_hook=payload.ending_hook,
            status=payload.status or "draft",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        _commit_plan(session)
        session.refresh(row)
        logger.info("chapter outline created")
        return _outline_response(row)

    if payload.expected_revision != row.revision:
        raise RevisionConflict(_CONFLICT)
    changed = _assign_outline_fields(row, payload)
    if changed:
        row.revision += 1
        row.updated_at = now
        _commit_plan(session)
        session.refresh(row)
        logger.info("chapter outline updated")
    return _outline_response(row)


def confirm_chapter_outline(
    session: Session,
    chapter_id: str,
    payload: PlanningConfirm,
) -> ChapterOutlineResponse:
    chapter = _require_chapter(session, chapter_id)
    row = _outline_for_chapter(session, chapter)
    if row is None:
        raise NotFound("这一章还没有大纲。")
    _mark_confirmed(session, row, payload.expected_revision)
    return _outline_response(row)


def list_scenes(session: Session, chapter_id: str) -> list[SceneCardResponse]:
    chapter = _require_chapter(session, chapter_id)
    return [_scene_response(session, row) for row in _scene_rows(session, chapter)]


def create_scene(
    session: Session,
    chapter_id: str,
    payload: SceneCardWrite,
) -> SceneCardResponse:
    chapter = _require_chapter(session, chapter_id)
    if payload.expected_revision is not None:
        raise RevisionConflict(_CONFLICT)
    location_id = _checked_location(session, chapter.novel_id, payload.location_entity_id)
    characters = _checked_characters(session, chapter.novel_id, payload.character_entity_ids)
    now = _now()
    row = SceneCard(
        id=_new_id(),
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        sort_order=_next_sort(session, chapter.id),
        goal=payload.goal,
        location_entity_id=location_id,
        character_entity_ids=characters,
        conflict=payload.conflict,
        turning_point=payload.turning_point,
        expected_outcome=payload.expected_outcome,
        must_convey=payload.must_convey,
        must_not_reveal=payload.must_not_reveal,
        status=payload.status,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    _commit_plan(session)
    session.refresh(row)
    logger.info("scene card created")
    return _scene_response(session, row)


def update_scene(
    session: Session,
    scene_id: str,
    payload: SceneCardPatch,
) -> SceneCardResponse:
    row = _require_scene(session, scene_id)
    if payload.expected_revision != row.revision:
        raise RevisionConflict(_CONFLICT)
    fields = payload.model_fields_set
    changed = False
    if "goal" in fields and payload.goal != row.goal:
        row.goal = payload.goal
        changed = True
    if "location_entity_id" in fields:
        location_id = _checked_location(session, row.novel_id, payload.location_entity_id)
        if location_id != row.location_entity_id:
            row.location_entity_id = location_id
            changed = True
    if "character_entity_ids" in fields and payload.character_entity_ids is not None:
        characters = _checked_characters(session, row.novel_id, payload.character_entity_ids)
        if characters != _id_list(row.character_entity_ids):
            row.character_entity_ids = characters
            changed = True
    for name in (
        "conflict",
        "turning_point",
        "expected_outcome",
        "must_convey",
        "must_not_reveal",
    ):
        if name in fields and getattr(payload, name) != getattr(row, name):
            setattr(row, name, getattr(payload, name))
            changed = True
    if "status" in fields and payload.status is not None and payload.status != row.status:
        row.status = payload.status
        changed = True
    if changed:
        row.revision += 1
        row.updated_at = _now()
        _commit_plan(session)
        session.refresh(row)
        logger.info("scene card updated")
    return _scene_response(session, row)


def delete_scene(session: Session, scene_id: str) -> None:
    row = _require_scene(session, scene_id)
    chapter_id = row.chapter_id
    novel_id = row.novel_id
    session.delete(row)
    session.flush()
    remaining = _scene_rows_for(session, novel_id, chapter_id)
    now = _now()
    for index, item in enumerate(remaining):
        item.sort_order = index
        item.updated_at = now
    _commit_plan(session)
    logger.info("scene card deleted")


def reorder_scenes(
    session: Session,
    chapter_id: str,
    payload: SceneReorder,
) -> list[SceneCardResponse]:
    chapter = _require_chapter(session, chapter_id)
    rows = _scene_rows(session, chapter)
    by_id = {row.id: row for row in rows}
    if len(payload.scene_ids) != len(by_id) or set(payload.scene_ids) != set(by_id):
        raise InvalidReference("重排必须包含这一章的全部场景，且不能包含其他场景。")
    now = _now()
    for index, scene_id in enumerate(payload.scene_ids):
        row = by_id[scene_id]
        if row.novel_id != chapter.novel_id:
            raise InvalidReference("场景不属于这本作品。")
        row.sort_order = index
        row.updated_at = now
    _commit_plan(session)
    logger.info("scene cards reordered")
    return [_scene_response(session, by_id[scene_id]) for scene_id in payload.scene_ids]


def list_story_arcs(session: Session, novel_id: str) -> list[StoryArcResponse]:
    _require_novel(session, novel_id)
    return [_arc_response(row) for row in _arc_rows(session, novel_id)]


def create_story_arc(
    session: Session,
    novel_id: str,
    payload: StoryArcCreate,
) -> StoryArcResponse:
    _require_novel(session, novel_id)
    now = _now()
    row = StoryArc(
        id=_new_id(),
        novel_id=novel_id,
        arc_type=payload.arc_type,
        title=payload.title,
        summary=payload.summary,
        sort_order=_next_arc_sort(session, novel_id),
        status=payload.status or "draft",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    _commit_plan(session)
    session.refresh(row)
    logger.info("story arc created")
    return _arc_response(row)


def update_story_arc(
    session: Session,
    arc_id: str,
    payload: StoryArcPatch,
) -> StoryArcResponse:
    row = _require_arc(session, arc_id)
    if payload.expected_revision != row.revision:
        raise RevisionConflict(_CONFLICT)
    if "title" in payload.model_fields_set and payload.title is None:
        raise InvalidReference("故事线标题不能为空。")
    changed = _assign_arc_fields(row, payload)
    if changed:
        row.revision += 1
        row.updated_at = _now()
        _commit_plan(session)
        session.refresh(row)
        logger.info("story arc updated")
    return _arc_response(row)


def delete_story_arc(session: Session, arc_id: str) -> None:
    row = _require_arc(session, arc_id)
    novel_id = row.novel_id
    session.delete(row)
    session.flush()
    now = _now()
    for index, item in enumerate(_arc_rows(session, novel_id)):
        item.sort_order = index
        item.updated_at = now
    _commit_plan(session)
    logger.info("story arc deleted")


def reorder_story_arcs(
    session: Session,
    novel_id: str,
    payload: StoryArcReorder,
) -> list[StoryArcResponse]:
    _require_novel(session, novel_id)
    rows = _arc_rows(session, novel_id)
    by_id = {row.id: row for row in rows}
    if len(payload.arc_ids) != len(by_id) or set(payload.arc_ids) != set(by_id):
        raise InvalidReference("重排必须包含这本作品的全部故事线，且不能包含其他作品。")
    now = _now()
    for index, arc_id in enumerate(payload.arc_ids):
        row = by_id[arc_id]
        if row.novel_id != novel_id:
            raise InvalidReference("故事线不属于这本作品。")
        row.sort_order = index
        row.updated_at = now
    _commit_plan(session)
    logger.info("story arcs reordered")
    return [_arc_response(by_id[arc_id]) for arc_id in payload.arc_ids]


def confirm_story_arc(
    session: Session,
    arc_id: str,
    payload: PlanningConfirm,
) -> StoryArcResponse:
    row = _require_arc(session, arc_id)
    _mark_confirmed(session, row, payload.expected_revision)
    return _arc_response(row)


def list_volume_outlines(session: Session, novel_id: str) -> list[VolumeOutlineResponse]:
    _require_novel(session, novel_id)
    stmt = (
        select(VolumeOutline)
        .join(Volume, Volume.id == VolumeOutline.volume_id)
        .where(
            VolumeOutline.novel_id == novel_id,
            Volume.novel_id == novel_id,
        )
        .order_by(Volume.sort_order.asc(), VolumeOutline.id.asc())
    )
    return [_volume_response(row) for row in session.scalars(stmt).all()]


def get_volume_outline(session: Session, volume_id: str) -> VolumeOutlineView:
    volume = _require_volume(session, volume_id)
    row = _outline_for_volume(session, volume)
    return VolumeOutlineView(
        novel_id=volume.novel_id,
        volume_id=volume.id,
        outline=_volume_response(row) if row is not None else None,
    )


def save_volume_outline(
    session: Session,
    volume_id: str,
    payload: VolumeOutlineWrite,
) -> VolumeOutlineResponse:
    volume = _require_volume(session, volume_id)
    row = _outline_for_volume(session, volume)
    now = _now()
    if row is None:
        if payload.expected_revision is not None:
            raise RevisionConflict(_CONFLICT)
        row = VolumeOutline(
            id=_new_id(),
            novel_id=volume.novel_id,
            volume_id=volume.id,
            goal=payload.goal,
            key_events=payload.key_events,
            start_state=payload.start_state,
            end_state=payload.end_state,
            status=payload.status or "draft",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        _commit_plan(session)
        session.refresh(row)
        logger.info("volume outline created")
        return _volume_response(row)

    if payload.expected_revision != row.revision:
        raise RevisionConflict(_CONFLICT)
    changed = _assign_volume_fields(row, payload)
    if changed:
        row.revision += 1
        row.updated_at = now
        _commit_plan(session)
        session.refresh(row)
        logger.info("volume outline updated")
    return _volume_response(row)


def confirm_volume_outline(
    session: Session,
    volume_id: str,
    payload: PlanningConfirm,
) -> VolumeOutlineResponse:
    volume = _require_volume(session, volume_id)
    row = _outline_for_volume(session, volume)
    if row is None:
        raise NotFound("这一卷还没有大纲。")
    _mark_confirmed(session, row, payload.expected_revision)
    return _volume_response(row)


def preview_outline_candidate(
    session: Session,
    chapter_id: str,
    payload: OutlineCandidateRequest,
) -> OutlineCandidatePreview:
    """Return a preview. This does not write plans or the manuscript."""

    chapter = _require_chapter(session, chapter_id)
    mode, _model_name = _outline_provider_mode(session, payload)
    draft = _candidate_draft(session, chapter, payload, mode)
    simulated = mode == "mock"
    note = (
        "模拟模型生成，尚未写入正式大纲，也不是已确认事实。"
        if simulated
        else "模型候选尚未写入正式大纲，也不是已确认事实。"
    )
    logger.info("outline candidate previewed")
    return OutlineCandidatePreview(
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        provider_mode="mock" if simulated else "openai_compatible",
        simulated=simulated,
        confirmed=False,
        manuscript_changed=False,
        written=False,
        note=note,
        goal=draft.goal,
        must_advance=draft.must_advance,
        required_events=draft.required_events,
        allowed_reveals=draft.allowed_reveals,
        forbidden_reveals=draft.forbidden_reveals,
        target_words=draft.target_words,
        ending_hook=draft.ending_hook,
        scenes=draft.scenes if payload.include_scenes else [],
    )


def accept_outline_candidate(
    session: Session,
    chapter_id: str,
    payload: OutlineCandidateAccept,
) -> OutlineCandidateAcceptResult:
    """Write the preview as a draft outline. Never confirms it or edits the manuscript."""

    chapter = _require_chapter(session, chapter_id)
    before_revision = chapter.revision
    outline_payload = ChapterOutlineWrite(
        goal=payload.goal,
        must_advance=payload.must_advance,
        required_events=payload.required_events,
        allowed_reveals=payload.allowed_reveals,
        forbidden_reveals=payload.forbidden_reveals,
        target_words=payload.target_words,
        ending_hook=payload.ending_hook,
        status="draft",
        expected_revision=payload.expected_revision,
    )
    outline = save_chapter_outline(session, chapter_id, outline_payload)
    if outline.status != "draft":
        stored = _outline_for_chapter(session, chapter)
        if stored is not None and stored.status != "draft":
            stored.status = "draft"
            stored.revision += 1
            stored.updated_at = _now()
            _commit_plan(session)
            session.refresh(stored)
            outline = _outline_response(stored)
    created_scenes: list[SceneCardResponse] = []
    for scene in payload.scenes:
        created_scenes.append(
            create_scene(
                session,
                chapter_id,
                SceneCardWrite(
                    goal=scene.goal,
                    conflict=scene.conflict,
                    turning_point=scene.turning_point,
                    expected_outcome=scene.expected_outcome,
                    must_convey=scene.must_convey,
                    must_not_reveal=scene.must_not_reveal,
                    status="draft",
                ),
            )
        )
    session.refresh(chapter)
    if chapter.revision != before_revision:
        raise InvalidReference("大纲候选不能修改正文。")
    logger.info("outline candidate accepted as draft")
    return OutlineCandidateAcceptResult(
        outline=outline,
        scenes=created_scenes,
        manuscript_changed=False,
    )


def mark_volume_outline_stale(session: Session, novel_id: str, volume_id: str | None) -> None:
    """Expire a confirmed volume outline. Draft and archived rows stay as they are."""

    if volume_id is None:
        return
    session.execute(
        update(VolumeOutline)
        .where(
            VolumeOutline.novel_id == novel_id,
            VolumeOutline.volume_id == volume_id,
            VolumeOutline.status == "confirmed",
        )
        .values(status="stale", revision=VolumeOutline.revision + 1, updated_at=_now())
    )


def discard_volume_outline(session: Session, volume_id: str) -> None:
    """Drop the outline row before its volume is deleted. Does not commit."""

    session.execute(delete(VolumeOutline).where(VolumeOutline.volume_id == volume_id))


def _mark_confirmed(
    session: Session,
    row: StoryPlan | ChapterOutline | VolumeOutline | StoryArc,
    expected_revision: int,
) -> None:
    if row.revision != expected_revision:
        raise RevisionConflict(_CONFLICT)
    if row.status != "confirmed":
        row.status = "confirmed"
        row.revision += 1
        row.updated_at = _now()
        _commit_plan(session)
        session.refresh(row)
        logger.info("planning row confirmed")


def _assign_story_fields(row: StoryPlan, payload: StoryPlanWrite) -> bool:
    changed = False
    fields = payload.model_fields_set
    for name in ("logline", "body", "ending_intent"):
        if name in fields and getattr(payload, name) != getattr(row, name):
            setattr(row, name, getattr(payload, name))
            changed = True
    explicit_status = "status" in fields and payload.status is not None
    if explicit_status and payload.status != row.status:
        row.status = payload.status or row.status
        changed = True
    elif changed and row.status == "confirmed":
        row.status = "draft"
    return changed


def _assign_outline_fields(row: ChapterOutline, payload: ChapterOutlineWrite) -> bool:
    changed = False
    fields = payload.model_fields_set
    for name in (
        "goal",
        "must_advance",
        "required_events",
        "allowed_reveals",
        "forbidden_reveals",
        "target_words",
        "ending_hook",
    ):
        if name in fields and getattr(payload, name) != getattr(row, name):
            setattr(row, name, getattr(payload, name))
            changed = True
    explicit_status = "status" in fields and payload.status is not None
    if explicit_status and payload.status != row.status:
        row.status = payload.status or row.status
        changed = True
    elif changed and row.status == "confirmed":
        row.status = "draft"
    return changed


def _assign_arc_fields(row: StoryArc, payload: StoryArcPatch) -> bool:
    changed = False
    fields = payload.model_fields_set
    if "arc_type" in fields and payload.arc_type is not None and payload.arc_type != row.arc_type:
        row.arc_type = payload.arc_type
        changed = True
    if "title" in fields and payload.title is not None and payload.title != row.title:
        row.title = payload.title
        changed = True
    if "summary" in fields and payload.summary != row.summary:
        row.summary = payload.summary
        changed = True
    explicit_status = "status" in fields and payload.status is not None
    if explicit_status and payload.status != row.status:
        row.status = payload.status or row.status
        changed = True
    elif changed and row.status == "confirmed":
        row.status = "draft"
    return changed


def _assign_volume_fields(row: VolumeOutline, payload: VolumeOutlineWrite) -> bool:
    changed = False
    fields = payload.model_fields_set
    for name in ("goal", "key_events", "start_state", "end_state"):
        if name in fields and getattr(payload, name) != getattr(row, name):
            setattr(row, name, getattr(payload, name))
            changed = True
    explicit_status = "status" in fields and payload.status is not None
    if explicit_status and payload.status != row.status:
        row.status = payload.status or row.status
        changed = True
    elif changed and row.status == "confirmed":
        row.status = "draft"
    return changed


class _CandidateDraft:
    def __init__(
        self,
        *,
        goal: str | None,
        must_advance: str | None,
        required_events: str | None,
        allowed_reveals: str | None,
        forbidden_reveals: str | None,
        target_words: int | None,
        ending_hook: str | None,
        scenes: list[OutlineCandidateScene],
    ) -> None:
        self.goal = goal
        self.must_advance = must_advance
        self.required_events = required_events
        self.allowed_reveals = allowed_reveals
        self.forbidden_reveals = forbidden_reveals
        self.target_words = target_words
        self.ending_hook = ending_hook
        self.scenes = scenes


def _candidate_draft(
    session: Session,
    chapter: Chapter,
    payload: OutlineCandidateRequest,
    mode: str,
) -> _CandidateDraft:
    if mode == "mock":
        return _mock_candidate(chapter, payload.include_scenes)
    from app.services.memory import (
        _endpoint_from_config,
        _public_provider_error,
        _require_config,
        generate_analysis_text,
    )

    config = _require_config(session, payload.model_config_id)
    prompt = _outline_prompt(chapter, payload.include_scenes)
    try:
        raw = generate_analysis_text(endpoint=_endpoint_from_config(config), prompt=prompt)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    return _draft_from_json(raw, payload.include_scenes)


def _outline_provider_mode(session: Session, payload: OutlineCandidateRequest) -> tuple[str, str]:
    from app.services.memory import _load_config, _require_config

    if payload.use_mock:
        if payload.model_config_id:
            config = _load_config(session, payload.model_config_id)
            if config.provider_type != "mock":
                raise ModelConfigInvalid("模拟生成不能绑定外部模型。")
        return "mock", "模拟模型"
    config = _require_config(session, payload.model_config_id)
    return "openai_compatible", config.model_name


def _mock_candidate(chapter: Chapter, include_scenes: bool) -> _CandidateDraft:
    title = chapter.title.strip() or "这一章"
    excerpt = " ".join(document_to_text(chapter.content).split())
    hint = excerpt[:40]
    advance = "让本章已经写下的情况发生变化"
    if hint:
        advance = f"顺着正文里的「{hint}」往前推进一步"
    scenes: list[OutlineCandidateScene] = []
    if include_scenes:
        scenes = [
            OutlineCandidateScene(
                goal=f"进入「{title}」",
                conflict="眼前的阻碍还没有解开",
                expected_outcome="人物被迫做一个小决定",
            ),
            OutlineCandidateScene(
                goal="把阻碍推进一步",
                turning_point="出现一个下一章能接住的问题",
                must_not_reveal="不要提前写出后文才知道的结局",
            ),
        ]
    return _CandidateDraft(
        goal=f"模拟候选：推进「{title}」",
        must_advance=advance,
        required_events="出现一个可被下一章接住的具体事件",
        allowed_reveals=None,
        forbidden_reveals="不要提前写出后文才知道的结局",
        target_words=None,
        ending_hook="在本章末尾留下一个未完成的问题",
        scenes=scenes,
    )


def _outline_prompt(chapter: Chapter, include_scenes: bool) -> str:
    excerpt = document_to_text(chapter.content).strip()[:1200]
    scene_rule = (
        "scenes 给 1 到 3 个对象，字段 goal、conflict、turning_point、"
        "expected_outcome、must_convey、must_not_reveal 均可为空字符串。"
        if include_scenes
        else "scenes 必须是空数组。"
    )
    return (
        "只返回一个 JSON 对象，不要写 Markdown。不要改正文。\n"
        "字段：goal、must_advance、required_events、allowed_reveals、"
        "forbidden_reveals、target_words、ending_hook、scenes。\n"
        "target_words 是整数或 null。这是大纲候选，不是已确认事实。\n"
        f"{scene_rule}\n"
        f"章节标题：{chapter.title}\n"
        f"正文摘录：{excerpt or '（这一章还没有正文）'}"
    )


def _draft_from_json(raw: str, include_scenes: bool) -> _CandidateDraft:
    from pydantic import ValidationError

    try:
        parsed = _load_candidate_json(raw)
        accepted = OutlineCandidateAccept.model_validate(parsed)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的大纲候选。正式大纲和正文都没有改动。",
            502,
        ) from exc
    scenes = accepted.scenes if include_scenes else []
    return _CandidateDraft(
        goal=accepted.goal,
        must_advance=accepted.must_advance,
        required_events=accepted.required_events,
        allowed_reveals=accepted.allowed_reveals,
        forbidden_reveals=accepted.forbidden_reveals,
        target_words=accepted.target_words,
        ending_hook=accepted.ending_hook,
        scenes=scenes,
    )


def _load_candidate_json(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text[: text.rfind("```")]
    return json.loads(text.strip())


def _story_plan(session: Session, novel_id: str) -> StoryPlan | None:
    return session.scalars(select(StoryPlan).where(StoryPlan.novel_id == novel_id)).first()


def _arc_rows(session: Session, novel_id: str) -> list[StoryArc]:
    stmt = (
        select(StoryArc)
        .where(StoryArc.novel_id == novel_id)
        .order_by(StoryArc.sort_order.asc(), StoryArc.id.asc())
    )
    return list(session.scalars(stmt).all())


def _next_arc_sort(session: Session, novel_id: str) -> int:
    orders = list(
        session.scalars(select(StoryArc.sort_order).where(StoryArc.novel_id == novel_id)).all()
    )
    if not orders:
        return 0
    return max(orders) + 1


def _require_arc(session: Session, arc_id: str) -> StoryArc:
    row = session.get(StoryArc, arc_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("故事线不存在。")
    return row


def _require_volume(session: Session, volume_id: str) -> Volume:
    volume = catalog_repo.get_volume(session, volume_id)
    if volume is None or catalog_repo.get_novel(session, volume.novel_id) is None:
        raise NotFound("卷不存在。")
    return volume


def _outline_for_volume(session: Session, volume: Volume) -> VolumeOutline | None:
    row = session.scalars(select(VolumeOutline).where(VolumeOutline.volume_id == volume.id)).first()
    if row is None:
        return None
    if row.novel_id != volume.novel_id:
        raise InvalidReference("卷大纲不属于这本作品。")
    return row


def _outline_for_chapter(session: Session, chapter: Chapter) -> ChapterOutline | None:
    row = session.scalars(
        select(ChapterOutline).where(ChapterOutline.chapter_id == chapter.id)
    ).first()
    if row is None:
        return None
    if row.novel_id != chapter.novel_id:
        raise InvalidReference("章节大纲不属于这本作品。")
    return row


def _scene_rows(session: Session, chapter: Chapter) -> list[SceneCard]:
    return _scene_rows_for(session, chapter.novel_id, chapter.id)


def _scene_rows_for(session: Session, novel_id: str, chapter_id: str) -> list[SceneCard]:
    stmt = (
        select(SceneCard)
        .where(SceneCard.chapter_id == chapter_id, SceneCard.novel_id == novel_id)
        .order_by(SceneCard.sort_order.asc(), SceneCard.id.asc())
    )
    return list(session.scalars(stmt).all())


def _next_sort(session: Session, chapter_id: str) -> int:
    stmt = select(SceneCard.sort_order).where(SceneCard.chapter_id == chapter_id)
    orders = list(session.scalars(stmt).all())
    if not orders:
        return 0
    return max(orders) + 1


def _require_scene(session: Session, scene_id: str) -> SceneCard:
    row = session.get(SceneCard, scene_id)
    if row is None:
        raise NotFound("场景卡片不存在。")
    chapter = catalog_repo.get_chapter(session, row.chapter_id)
    if (
        chapter is None
        or chapter.novel_id != row.novel_id
        or catalog_repo.get_novel(session, row.novel_id) is None
    ):
        raise NotFound("场景卡片不存在。")
    return row


def _checked_location(session: Session, novel_id: str, entity_id: str | None) -> str | None:
    if entity_id is None:
        return None
    entity = _require_entity(session, novel_id, entity_id)
    if entity.entity_type != "location":
        raise InvalidReference("场景地点必须引用这本作品里已有的地点。")
    return entity.id


def _checked_characters(session: Session, novel_id: str, entity_ids: list[str]) -> list[str]:
    checked: list[str] = []
    for entity_id in entity_ids:
        entity = _require_entity(session, novel_id, entity_id)
        if entity.entity_type != "character":
            raise InvalidReference("出场人物必须引用这本作品里已有的人物。")
        checked.append(entity.id)
    return checked


def _require_entity(session: Session, novel_id: str, entity_id: str) -> StoryEntity:
    entity = session.get(StoryEntity, entity_id)
    if entity is None or entity.deleted_at is not None or entity.novel_id != novel_id:
        raise InvalidReference("设定不存在，或不属于这本作品。")
    return entity


def _require_novel(session: Session, novel_id: str) -> None:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")


def _require_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None or catalog_repo.get_novel(session, chapter.novel_id) is None:
        raise NotFound("章节不存在。")
    return chapter


def _arc_response(row: StoryArc) -> StoryArcResponse:
    return StoryArcResponse(
        id=row.id,
        novel_id=row.novel_id,
        arc_type=_arc_type(row.arc_type),
        title=row.title,
        summary=row.summary,
        sort_order=row.sort_order,
        status=_status(row.status),
        revision=row.revision,
        counts_as_fact=planning_counts_as_fact(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _volume_response(row: VolumeOutline) -> VolumeOutlineResponse:
    return VolumeOutlineResponse(
        id=row.id,
        novel_id=row.novel_id,
        volume_id=row.volume_id,
        goal=row.goal,
        key_events=row.key_events,
        start_state=row.start_state,
        end_state=row.end_state,
        status=_status(row.status),
        revision=row.revision,
        counts_as_fact=planning_counts_as_fact(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _arc_type(value: str) -> StoryArcType:
    if value in _ARC_TYPES:
        return cast(StoryArcType, value)
    return "other"


def _story_response(row: StoryPlan) -> StoryPlanResponse:
    return StoryPlanResponse(
        id=row.id,
        novel_id=row.novel_id,
        logline=row.logline,
        body=row.body,
        ending_intent=row.ending_intent,
        status=_status(row.status),
        revision=row.revision,
        counts_as_fact=planning_counts_as_fact(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _outline_response(row: ChapterOutline) -> ChapterOutlineResponse:
    return ChapterOutlineResponse(
        id=row.id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        goal=row.goal,
        must_advance=row.must_advance,
        required_events=row.required_events,
        allowed_reveals=row.allowed_reveals,
        forbidden_reveals=row.forbidden_reveals,
        target_words=row.target_words,
        ending_hook=row.ending_hook,
        status=_status(row.status),
        revision=row.revision,
        counts_as_fact=planning_counts_as_fact(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _scene_response(session: Session, row: SceneCard) -> SceneCardResponse:
    character_ids = _id_list(row.character_entity_ids)
    location = (
        _entity_ref(session, row.novel_id, row.location_entity_id)
        if row.location_entity_id is not None
        else None
    )
    return SceneCardResponse(
        id=row.id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        sort_order=row.sort_order,
        goal=row.goal,
        location_entity_id=row.location_entity_id,
        location=location,
        character_entity_ids=character_ids,
        characters=[_entity_ref(session, row.novel_id, entity_id) for entity_id in character_ids],
        conflict=row.conflict,
        turning_point=row.turning_point,
        expected_outcome=row.expected_outcome,
        must_convey=row.must_convey,
        must_not_reveal=row.must_not_reveal,
        status=_status(row.status),
        revision=row.revision,
        counts_as_fact=planning_counts_as_fact(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _entity_ref(session: Session, novel_id: str, entity_id: str) -> EntityRef:
    entity = session.get(StoryEntity, entity_id)
    if entity is None or entity.deleted_at is not None or entity.novel_id != novel_id:
        return EntityRef(id=entity_id, name=None, entity_type=None, available=False)
    return EntityRef(
        id=entity.id,
        name=entity.name,
        entity_type=entity.entity_type,
        available=True,
    )


def _id_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _status(value: str) -> PlanningStatus:
    if value in _STATUSES:
        return cast(PlanningStatus, value)
    return "draft"


def _commit_plan(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RevisionConflict(_CONFLICT) from None


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
