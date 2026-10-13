"""Catalog queries. Callers own the transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Chapter, Novel, Volume


def list_novels(session: Session) -> list[Novel]:
    stmt = (
        select(Novel)
        .where(Novel.deleted_at.is_(None))
        .order_by(Novel.updated_at.desc(), Novel.id.asc())
    )
    return list(session.scalars(stmt))


def get_novel(session: Session, novel_id: str) -> Novel | None:
    novel = session.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        return None
    return novel


def list_volumes(session: Session, novel_id: str) -> list[Volume]:
    stmt = (
        select(Volume)
        .where(Volume.novel_id == novel_id)
        .order_by(Volume.sort_order.asc(), Volume.id.asc())
    )
    return list(session.scalars(stmt))


def get_volume(session: Session, volume_id: str) -> Volume | None:
    return session.get(Volume, volume_id)


def list_chapters(session: Session, novel_id: str) -> list[Chapter]:
    stmt = (
        select(Chapter)
        .where(Chapter.novel_id == novel_id, Chapter.deleted_at.is_(None))
        .order_by(Chapter.sort_order.asc(), Chapter.id.asc())
    )
    return list(session.scalars(stmt))


def list_chapters_in_group(
    session: Session,
    novel_id: str,
    volume_id: str | None,
) -> list[Chapter]:
    stmt = select(Chapter).where(Chapter.novel_id == novel_id, Chapter.deleted_at.is_(None))
    if volume_id is None:
        stmt = stmt.where(Chapter.volume_id.is_(None))
    else:
        stmt = stmt.where(Chapter.volume_id == volume_id)
    stmt = stmt.order_by(Chapter.sort_order.asc(), Chapter.id.asc())
    return list(session.scalars(stmt))


def get_chapter(session: Session, chapter_id: str) -> Chapter | None:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None or chapter.deleted_at is not None:
        return None
    return chapter
