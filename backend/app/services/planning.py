"""Story planning. Writes never touch chapter text, revision, or versions.

A plan counts as a binding constraint only while its status is confirmed.
Draft, stale, and archived rows stay stored so the author can see them.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import InvalidReference, NotFound, RevisionConflict
from app.models.catalog import Chapter
from app.models.memory import StoryEntity
from app.models.planning import ChapterOutline, SceneCard, StoryPlan
from app.repositories import catalog as catalog_repo
from app.schemas.planning import (
    ChapterOutlineResponse,
    ChapterOutlineView,
    ChapterOutlineWrite,
    EntityRef,
    PlanningConfirm,
    PlanningStatus,
    SceneCardPatch,
    SceneCardResponse,
    SceneCardWrite,
    SceneReorder,
    StoryPlanResponse,
    StoryPlanView,
    StoryPlanWrite,
)

logger = logging.getLogger("app.planning")

_STATUSES = {"draft", "confirmed", "stale", "archived"}
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


def _mark_confirmed(
    session: Session,
    row: StoryPlan | ChapterOutline,
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


def _story_plan(session: Session, novel_id: str) -> StoryPlan | None:
    return session.scalars(select(StoryPlan).where(StoryPlan.novel_id == novel_id)).first()


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
