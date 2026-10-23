"""Foreshadowing and writing statistics. Neither path rewrites chapter text."""

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content import word_count
from app.core.errors import InvalidReference, NotFound
from app.models.catalog import Chapter
from app.models.quality import Foreshadowing, WritingGoal
from app.repositories import catalog as catalog_repo
from app.schemas.quality import (
    ChapterStat,
    ForeshadowingCreate,
    ForeshadowingPatch,
    ForeshadowingResponse,
    ForeshadowingStatus,
    NovelStatsResponse,
)

logger = logging.getLogger("app.quality")

_STATUSES = {"open", "planned", "resolved", "abandoned", "uncertain"}


def list_foreshadowing(
    session: Session,
    novel_id: str,
    status: str | None,
) -> list[ForeshadowingResponse]:
    _require_novel(session, novel_id)
    stmt = select(Foreshadowing).where(Foreshadowing.novel_id == novel_id)
    if status is not None:
        stmt = stmt.where(Foreshadowing.status == status)
    stmt = stmt.order_by(Foreshadowing.created_at.asc(), Foreshadowing.id.asc())
    return [_response(row) for row in session.scalars(stmt).all()]


def create_foreshadowing(
    session: Session,
    novel_id: str,
    payload: ForeshadowingCreate,
) -> ForeshadowingResponse:
    _require_novel(session, novel_id)
    _require_chapter(session, novel_id, payload.introduced_chapter_id)
    if payload.payoff_chapter_id is not None:
        _require_chapter(session, novel_id, payload.payoff_chapter_id)
    now = _now()
    row = Foreshadowing(
        id=str(uuid.uuid4()),
        novel_id=novel_id,
        introduced_chapter_id=payload.introduced_chapter_id,
        description=payload.description,
        status=payload.status,
        payoff_chapter_id=payload.payoff_chapter_id,
        evidence_quote=payload.evidence_quote,
        event_time_text=payload.event_time_text,
        character_discovered_text=payload.character_discovered_text,
        reader_revealed_text=payload.reader_revealed_text,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("foreshadowing created")
    return _response(row)


def update_foreshadowing(
    session: Session,
    foreshadowing_id: str,
    payload: ForeshadowingPatch,
) -> ForeshadowingResponse:
    row = session.get(Foreshadowing, foreshadowing_id)
    if row is None:
        raise NotFound("伏笔不存在。")
    fields = payload.model_fields_set
    if "introduced_chapter_id" in fields and payload.introduced_chapter_id is not None:
        _require_chapter(session, row.novel_id, payload.introduced_chapter_id)
        row.introduced_chapter_id = payload.introduced_chapter_id
    if "description" in fields and payload.description is not None:
        row.description = payload.description
    if "status" in fields and payload.status is not None:
        row.status = payload.status
    if "payoff_chapter_id" in fields:
        if payload.payoff_chapter_id is not None:
            _require_chapter(session, row.novel_id, payload.payoff_chapter_id)
        row.payoff_chapter_id = payload.payoff_chapter_id
    if "evidence_quote" in fields:
        row.evidence_quote = payload.evidence_quote
    if "event_time_text" in fields:
        row.event_time_text = payload.event_time_text
    if "character_discovered_text" in fields:
        row.character_discovered_text = payload.character_discovered_text
    if "reader_revealed_text" in fields:
        row.reader_revealed_text = payload.reader_revealed_text
    if fields:
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
    logger.info("foreshadowing updated")
    return _response(row)


def novel_stats(session: Session, novel_id: str) -> NovelStatsResponse:
    _require_novel(session, novel_id)
    chapters = catalog_repo.list_chapters(session, novel_id)
    items = [_chapter_stat(chapter) for chapter in chapters]
    goal = session.scalars(select(WritingGoal).where(WritingGoal.novel_id == novel_id)).first()
    return NovelStatsResponse(
        novel_id=novel_id,
        total_word_count=sum(item.word_count for item in items),
        chapter_count=len(items),
        target_words=goal.target_words if goal is not None else None,
        chapters=items,
    )


def set_writing_goal(session: Session, novel_id: str, target_words: int) -> NovelStatsResponse:
    _require_novel(session, novel_id)
    goal = session.scalars(select(WritingGoal).where(WritingGoal.novel_id == novel_id)).first()
    now = _now()
    if goal is None:
        session.add(
            WritingGoal(
                id=str(uuid.uuid4()),
                novel_id=novel_id,
                target_words=target_words,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        goal.target_words = target_words
        goal.updated_at = now
    session.commit()
    logger.info("writing goal saved")
    return novel_stats(session, novel_id)


def _chapter_stat(chapter: Chapter) -> ChapterStat:
    content = chapter.content if isinstance(chapter.content, dict) else {}
    return ChapterStat(
        chapter_id=chapter.id,
        title=chapter.title,
        volume_id=chapter.volume_id,
        sort_order=chapter.sort_order,
        word_count=word_count(content),
    )


def _require_novel(session: Session, novel_id: str) -> None:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")


def _require_chapter(session: Session, novel_id: str, chapter_id: str) -> Chapter:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None or chapter.novel_id != novel_id:
        raise InvalidReference("章节不存在，或不属于这本作品。")
    return chapter


def _response(row: Foreshadowing) -> ForeshadowingResponse:
    return ForeshadowingResponse(
        id=row.id,
        novel_id=row.novel_id,
        introduced_chapter_id=row.introduced_chapter_id,
        description=row.description,
        status=_status(row.status),
        payoff_chapter_id=row.payoff_chapter_id,
        evidence_quote=row.evidence_quote,
        event_time_text=row.event_time_text,
        character_discovered_text=row.character_discovered_text,
        reader_revealed_text=row.reader_revealed_text,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _status(value: str) -> ForeshadowingStatus:
    if value in _STATUSES:
        return cast(ForeshadowingStatus, value)
    return "uncertain"


def _now() -> datetime:
    return datetime.now(UTC)
