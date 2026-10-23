"""Novel, volume, and chapter use cases."""

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.content import (
    CANONICAL_CONTENT_FORMAT,
    CANONICAL_CONTENT_FORMAT_VERSION,
    canonical_dump,
    document_to_text,
    empty_document,
    validate_document,
    word_count,
)
from app.core.errors import InvalidReference, NotFound, RevisionConflict, TaskStateError
from app.core.manuscript import preview_text
from app.core.text_diff import TextHunk, diff_lines
from app.models.ai import AiTask
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume
from app.models.memory import MemoryChangeProposal
from app.models.quality import QualityIssue, QualityRepairCandidate
from app.repositories import catalog as catalog_repo
from app.schemas.catalog import (
    ChapterCreate,
    ChapterMove,
    ChapterRestore,
    ChapterWrite,
    NovelCreate,
    NovelUpdate,
    VolumeCreate,
    VolumeReorder,
    VolumeUpdate,
)
from app.services.chapter_shells import ShellChapter, duplicate_shell_ids, reusable_shell_id
from app.services.memory import mark_chapter_memory_stale
from app.services.planning import discard_volume_outline, mark_volume_outline_stale

logger = logging.getLogger("app.catalog")


@dataclass(frozen=True)
class ChapterVersionRecord:
    id: str
    chapter_id: str
    revision: int
    content_format: str
    content_format_version: int
    change_source: str
    change_note: str | None
    word_count: int
    preview: str
    ai_task_id: str | None
    repair_candidate_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class VersionDetail:
    record: ChapterVersionRecord
    text: str
    memory_proposal_ids: tuple[str, ...]


@dataclass(frozen=True)
class DiffSide:
    id: str | None
    revision: int
    change_source: str | None
    change_note: str | None
    created_at: datetime
    word_count: int
    label: str
    ai_task_id: str | None
    repair_candidate_id: str | None
    memory_proposal_ids: tuple[str, ...]


@dataclass(frozen=True)
class VersionDiff:
    left: DiffSide
    right: DiffSide
    hunks: tuple[TextHunk, ...]


def create_novel(session: Session, payload: NovelCreate) -> Novel:
    now = _now()
    novel = Novel(
        id=_new_id(),
        title=payload.title,
        genre=_blank_to_none(payload.genre),
        synopsis=_blank_to_none(payload.synopsis),
        style_guide=_blank_to_none(payload.style_guide),
        core_conflict=_blank_to_none(payload.core_conflict),
        status=payload.status,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(novel)
    session.commit()
    session.refresh(novel)
    logger.info("novel created")
    return novel


def list_novels(session: Session) -> list[Novel]:
    return catalog_repo.list_novels(session)


def get_novel(session: Session, novel_id: str) -> Novel:
    return _require_novel(session, novel_id)


def update_novel(session: Session, novel_id: str, payload: NovelUpdate) -> Novel:
    novel = _require_novel(session, novel_id)
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        novel.title = changes["title"]
    if "genre" in changes:
        novel.genre = _blank_to_none(changes["genre"])
    if "synopsis" in changes:
        novel.synopsis = _blank_to_none(changes["synopsis"])
    if "style_guide" in changes:
        novel.style_guide = _blank_to_none(changes["style_guide"])
    if "core_conflict" in changes:
        novel.core_conflict = _blank_to_none(changes["core_conflict"])
    if "status" in changes:
        novel.status = changes["status"]
    novel.updated_at = _now()
    session.commit()
    session.refresh(novel)
    return novel


def delete_novel(session: Session, novel_id: str) -> None:
    novel = _require_novel(session, novel_id)
    novel.deleted_at = _now()
    novel.updated_at = novel.deleted_at
    session.commit()
    logger.info("novel archived by soft delete")


def create_volume(session: Session, novel_id: str, payload: VolumeCreate) -> Volume:
    _require_novel(session, novel_id)
    existing = catalog_repo.list_volumes(session, novel_id)
    now = _now()
    volume = Volume(
        id=_new_id(),
        novel_id=novel_id,
        title=payload.title,
        sort_order=_next_sort(existing),
        created_at=now,
        updated_at=now,
    )
    session.add(volume)
    session.commit()
    session.refresh(volume)
    return volume


def list_volumes(session: Session, novel_id: str) -> list[Volume]:
    _require_novel(session, novel_id)
    return catalog_repo.list_volumes(session, novel_id)


def update_volume(session: Session, volume_id: str, payload: VolumeUpdate) -> Volume:
    volume = _require_volume(session, volume_id)
    _require_novel(session, volume.novel_id)
    volume.title = payload.title
    volume.updated_at = _now()
    session.commit()
    session.refresh(volume)
    return volume


def delete_volume(session: Session, volume_id: str) -> None:
    volume = _require_volume(session, volume_id)
    _require_novel(session, volume.novel_id)
    detached = catalog_repo.list_chapters_in_group(session, volume.novel_id, volume.id)
    unassigned = catalog_repo.list_chapters_in_group(session, volume.novel_id, None)
    _renumber(unassigned + detached, None)
    discard_volume_outline(session, volume.id)
    session.delete(volume)
    session.commit()


def reorder_volumes(session: Session, payload: VolumeReorder) -> list[Volume]:
    _require_novel(session, payload.novel_id)
    existing = catalog_repo.list_volumes(session, payload.novel_id)
    existing_ids = [volume.id for volume in existing]
    if len(payload.volume_ids) != len(set(payload.volume_ids)):
        raise InvalidReference("卷排序包含重复项。")
    if set(payload.volume_ids) != set(existing_ids):
        raise InvalidReference("卷排序必须包含这本作品的全部分卷，且不能包含其他作品。")
    order = {volume_id: index for index, volume_id in enumerate(payload.volume_ids)}
    now = _now()
    for volume in existing:
        volume.sort_order = order[volume.id]
        volume.updated_at = now
    session.commit()
    return catalog_repo.list_volumes(session, payload.novel_id)


def create_chapter(session: Session, novel_id: str, payload: ChapterCreate) -> Chapter:
    _require_novel(session, novel_id)
    _require_volume_in_novel(session, novel_id, payload.volume_id)
    group = catalog_repo.list_chapters_in_group(session, novel_id, payload.volume_id)
    reusable_id = reusable_shell_id(
        [_shell_ref(chapter) for chapter in group],
        payload.title,
        payload.volume_id,
    )
    if reusable_id is not None:
        return _require_chapter(session, reusable_id)
    document = empty_document()
    now = _now()
    chapter = Chapter(
        id=_new_id(),
        novel_id=novel_id,
        volume_id=payload.volume_id,
        title=payload.title,
        sort_order=_next_sort(group),
        content=document,
        content_format=CANONICAL_CONTENT_FORMAT,
        content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
        word_count=word_count(document),
        status=payload.status,
        revision=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(chapter)
    mark_volume_outline_stale(session, novel_id, payload.volume_id)
    session.commit()
    session.refresh(chapter)
    return chapter


def list_chapters(session: Session, novel_id: str) -> list[Chapter]:
    _require_novel(session, novel_id)
    return catalog_repo.list_chapters(session, novel_id)


def get_chapter(session: Session, chapter_id: str) -> Chapter:
    return _require_chapter(session, chapter_id)


def save_chapter(session: Session, chapter_id: str, payload: ChapterWrite) -> Chapter:
    chapter = _require_chapter(session, chapter_id)
    if chapter.revision != payload.revision:
        raise RevisionConflict()
    document = validate_document(copy.deepcopy(payload.content))
    title = chapter.title if payload.title is None else payload.title
    status = chapter.status if payload.status is None else payload.status
    content_changed = canonical_dump(document) != _canonical_content(chapter.content)
    meta_changed = title != chapter.title or status != chapter.status
    latest = catalog_repo.latest_version(session, chapter.id)
    needs_snapshot = payload.save_kind == "manual" and (
        latest is None or canonical_dump(document) != _canonical_content(latest.content_snapshot)
    )
    needs_write = content_changed or meta_changed
    if not needs_write and not needs_snapshot:
        return chapter

    new_revision = chapter.revision + 1 if needs_write else chapter.revision
    if needs_write:
        values: dict[str, object] = {
            "content": copy.deepcopy(document),
            "content_format": CANONICAL_CONTENT_FORMAT,
            "content_format_version": CANONICAL_CONTENT_FORMAT_VERSION,
            "word_count": word_count(document),
            "title": title,
            "status": status,
            "revision": new_revision,
            "updated_at": _now(),
        }
        result = cast(
            CursorResult[tuple[object, ...]],
            session.execute(
                update(Chapter)
                .where(
                    Chapter.id == chapter_id,
                    Chapter.revision == payload.revision,
                    Chapter.deleted_at.is_(None),
                )
                .values(**values)
            ),
        )
        if result.rowcount != 1:
            session.rollback()
            raise RevisionConflict()
    if needs_snapshot:
        _add_version(
            session,
            chapter_id=chapter.id,
            revision=new_revision,
            document=document,
            change_source="manual",
            change_note=_blank_to_none(payload.change_note),
        )
    if needs_write:
        mark_chapter_memory_stale(session, chapter.id, new_revision)
    _commit_version_write(session, wrote_chapter=needs_write)
    return _reload_chapter(session, chapter_id)


def list_chapter_versions(session: Session, chapter_id: str) -> list[ChapterVersionRecord]:
    _require_chapter(session, chapter_id)
    return [_version_record(row) for row in catalog_repo.list_versions(session, chapter_id)]


def get_chapter_version(session: Session, chapter_id: str, version_id: str) -> VersionDetail:
    chapter = _require_chapter(session, chapter_id)
    version = _require_version(session, chapter.id, version_id)
    record = _version_record(version)
    return VersionDetail(
        record=record,
        text=_version_text(version),
        memory_proposal_ids=tuple(_memory_proposal_ids(session, chapter.id, version.revision)),
    )


def diff_chapter_versions(
    session: Session,
    chapter_id: str,
    left_id: str,
    right_id: str,
) -> VersionDiff:
    chapter = _require_chapter(session, chapter_id)
    if left_id == right_id:
        raise InvalidReference("请选择两个不同的版本或当前正文。")
    left = _diff_side(session, chapter, left_id)
    right = _diff_side(session, chapter, right_id)
    hunks = tuple(
        diff_lines(_side_text(session, chapter, left), _side_text(session, chapter, right))
    )
    return VersionDiff(left=left, right=right, hunks=hunks)


def restore_chapter(session: Session, chapter_id: str, payload: ChapterRestore) -> Chapter:
    chapter = _require_chapter(session, chapter_id)
    if chapter.revision != payload.revision:
        raise RevisionConflict()
    version = catalog_repo.get_version(session, payload.version_id)
    if version is None or version.chapter_id != chapter.id:
        raise NotFound("版本不存在。")
    document = validate_document(copy.deepcopy(version.content_snapshot))
    new_revision = chapter.revision + 1
    result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(Chapter)
            .where(
                Chapter.id == chapter.id,
                Chapter.revision == payload.revision,
                Chapter.deleted_at.is_(None),
            )
            .values(
                content=copy.deepcopy(document),
                content_format=CANONICAL_CONTENT_FORMAT,
                content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
                word_count=word_count(document),
                revision=new_revision,
                updated_at=_now(),
            )
        ),
    )
    if result.rowcount != 1:
        session.rollback()
        raise RevisionConflict()
    _add_version(
        session,
        chapter_id=chapter.id,
        revision=new_revision,
        document=document,
        change_source="restore",
        change_note=f"恢复自修订 {version.revision}",
        content_format_version=version.content_format_version,
    )
    mark_chapter_memory_stale(session, chapter.id, new_revision)
    _commit_version_write(session, wrote_chapter=True)
    logger.info("chapter restored")
    return _reload_chapter(session, chapter.id)


def apply_accepted_candidate(
    session: Session,
    chapter_id: str,
    *,
    expected_revision: int,
    document: dict[str, object],
    change_note: str | None,
    ai_task_id: str | None = None,
    repair_candidate_id: str | None = None,
    repair_issue_id: str | None = None,
) -> Chapter:
    """Write an accepted candidate in one transaction with its resolution.

    A failure rolls the chapter, snapshot, task resolution, and repair status
    back together. Callers must not commit a partial accept before this returns.
    """

    try:
        chapter = _require_chapter(session, chapter_id)
        if chapter.revision != expected_revision:
            raise RevisionConflict()
        validated = validate_document(copy.deepcopy(document))
        new_revision = chapter.revision + 1
        result = cast(
            CursorResult[tuple[object, ...]],
            session.execute(
                update(Chapter)
                .where(
                    Chapter.id == chapter.id,
                    Chapter.revision == expected_revision,
                    Chapter.deleted_at.is_(None),
                )
                .values(
                    content=copy.deepcopy(validated),
                    content_format=CANONICAL_CONTENT_FORMAT,
                    content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
                    word_count=word_count(validated),
                    revision=new_revision,
                    updated_at=_now(),
                )
            ),
        )
        if result.rowcount != 1:
            raise RevisionConflict()
        _add_version(
            session,
            chapter_id=chapter.id,
            revision=new_revision,
            document=validated,
            change_source="ai_accepted",
            change_note=change_note,
            ai_task_id=ai_task_id,
            repair_candidate_id=repair_candidate_id,
        )
        if ai_task_id is not None:
            _claim_ai_resolution(session, ai_task_id, chapter)
        if repair_candidate_id is not None:
            _claim_repair(session, repair_candidate_id, repair_issue_id, chapter, new_revision)
        mark_chapter_memory_stale(session, chapter.id, new_revision)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RevisionConflict() from None
    except Exception:
        session.rollback()
        raise
    logger.info("ai candidate accepted")
    return _reload_chapter(session, chapter_id)


def cleanup_duplicate_shells(session: Session, novel_id: str) -> int:
    """Delete extra empty shells that share a title. One written chapter, or one shell, stays."""

    _require_novel(session, novel_id)
    chapters = catalog_repo.list_chapters(session, novel_id)
    remove = set(duplicate_shell_ids([_shell_ref(chapter) for chapter in chapters]))
    if not remove:
        return 0
    now = _now()
    volumes: set[str | None] = set()
    for chapter in chapters:
        if chapter.id not in remove:
            continue
        chapter.deleted_at = now
        chapter.updated_at = now
        volumes.add(chapter.volume_id)
    session.flush()
    for volume_id in volumes:
        remaining = catalog_repo.list_chapters_in_group(session, novel_id, volume_id)
        _renumber(remaining, volume_id)
        mark_volume_outline_stale(session, novel_id, volume_id)
    session.commit()
    return len(remove)


def delete_chapter(session: Session, chapter_id: str) -> None:
    chapter = _require_chapter(session, chapter_id)
    volume_id = chapter.volume_id
    novel_id = chapter.novel_id
    chapter.deleted_at = _now()
    chapter.updated_at = chapter.deleted_at
    session.flush()
    remaining = catalog_repo.list_chapters_in_group(session, novel_id, volume_id)
    _renumber(remaining, volume_id)
    mark_volume_outline_stale(session, novel_id, volume_id)
    session.commit()


def move_chapter(session: Session, chapter_id: str, payload: ChapterMove) -> Chapter:
    chapter = _require_chapter(session, chapter_id)
    _require_volume_in_novel(session, chapter.novel_id, payload.volume_id)
    source_volume_id = chapter.volume_id
    source = [
        item
        for item in catalog_repo.list_chapters_in_group(session, chapter.novel_id, source_volume_id)
        if item.id != chapter.id
    ]
    if source_volume_id == payload.volume_id:
        target = source
    else:
        target = [
            item
            for item in catalog_repo.list_chapters_in_group(
                session, chapter.novel_id, payload.volume_id
            )
            if item.id != chapter.id
        ]
    target.insert(min(payload.sort_order, len(target)), chapter)
    _renumber(target, payload.volume_id)
    if source_volume_id != payload.volume_id:
        _renumber(source, source_volume_id)
    mark_volume_outline_stale(session, chapter.novel_id, source_volume_id)
    mark_volume_outline_stale(session, chapter.novel_id, payload.volume_id)
    session.commit()
    session.refresh(chapter)
    return chapter


def duplicate_chapter(session: Session, chapter_id: str) -> Chapter:
    source = _require_chapter(session, chapter_id)
    group = catalog_repo.list_chapters_in_group(session, source.novel_id, source.volume_id)
    now = _now()
    content = validate_document(copy.deepcopy(source.content))
    chapter = Chapter(
        id=_new_id(),
        novel_id=source.novel_id,
        volume_id=source.volume_id,
        title=_copy_title(source.title),
        sort_order=_next_sort(group),
        content=content,
        content_format=CANONICAL_CONTENT_FORMAT,
        content_format_version=CANONICAL_CONTENT_FORMAT_VERSION,
        word_count=word_count(content),
        status=source.status,
        revision=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(chapter)
    mark_volume_outline_stale(session, source.novel_id, source.volume_id)
    session.commit()
    session.refresh(chapter)
    return chapter


def _add_version(
    session: Session,
    *,
    chapter_id: str,
    revision: int,
    document: dict[str, object],
    change_source: str,
    change_note: str | None,
    content_format_version: int = CANONICAL_CONTENT_FORMAT_VERSION,
    ai_task_id: str | None = None,
    repair_candidate_id: str | None = None,
) -> None:
    session.add(
        ChapterVersion(
            id=_new_id(),
            chapter_id=chapter_id,
            revision=revision,
            content_snapshot=copy.deepcopy(document),
            content_format=CANONICAL_CONTENT_FORMAT,
            content_format_version=content_format_version,
            change_source=change_source,
            change_note=change_note,
            ai_task_id=ai_task_id,
            repair_candidate_id=repair_candidate_id,
            created_at=_now(),
        )
    )
    logger.info("chapter version recorded")


def _claim_ai_resolution(session: Session, task_id: str, chapter: Chapter) -> None:
    result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(AiTask)
            .where(
                AiTask.id == task_id,
                AiTask.chapter_id == chapter.id,
                AiTask.novel_id == chapter.novel_id,
                AiTask.status.in_(("completed", "cancelled")),
                AiTask.resolution.is_(None),
            )
            .values(resolution="accepted")
        ),
    )
    if result.rowcount != 1:
        raise TaskStateError("这份候选已经处理过。")


def _claim_repair(
    session: Session,
    candidate_id: str,
    issue_id: str | None,
    chapter: Chapter,
    new_revision: int,
) -> None:
    now = _now()
    result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(QualityRepairCandidate)
            .where(
                QualityRepairCandidate.id == candidate_id,
                QualityRepairCandidate.status == "proposed",
                QualityRepairCandidate.chapter_id == chapter.id,
                QualityRepairCandidate.novel_id == chapter.novel_id,
            )
            .values(status="accepted", updated_at=now)
        ),
    )
    if result.rowcount != 1:
        raise TaskStateError("这份建议已经处理过。")
    if issue_id is None:
        return
    issue_result = cast(
        CursorResult[tuple[object, ...]],
        session.execute(
            update(QualityIssue)
            .where(
                QualityIssue.id == issue_id,
                QualityIssue.novel_id == chapter.novel_id,
                QualityIssue.status != "expired",
            )
            .values(status="fixed", fixed_revision=new_revision, updated_at=now)
        ),
    )
    if issue_result.rowcount != 1:
        raise TaskStateError("问题已过期，请先重新检查。")


def _require_version(session: Session, chapter_id: str, version_id: str) -> ChapterVersion:
    version = catalog_repo.get_version(session, version_id)
    if version is None or version.chapter_id != chapter_id:
        raise NotFound("版本不存在。")
    return version


def _diff_side(session: Session, chapter: Chapter, side_id: str) -> DiffSide:
    if side_id == "current":
        document = chapter.content if isinstance(chapter.content, dict) else empty_document()
        return DiffSide(
            id=None,
            revision=chapter.revision,
            change_source=None,
            change_note=None,
            created_at=chapter.updated_at,
            word_count=word_count(document),
            label="当前正文",
            ai_task_id=None,
            repair_candidate_id=None,
            memory_proposal_ids=tuple(_memory_proposal_ids(session, chapter.id, chapter.revision)),
        )
    version = _require_version(session, chapter.id, side_id)
    record = _version_record(version)
    return DiffSide(
        id=record.id,
        revision=record.revision,
        change_source=record.change_source,
        change_note=record.change_note,
        created_at=record.created_at,
        word_count=record.word_count,
        label=f"修订 {record.revision}",
        ai_task_id=record.ai_task_id,
        repair_candidate_id=record.repair_candidate_id,
        memory_proposal_ids=tuple(_memory_proposal_ids(session, chapter.id, record.revision)),
    )


def _side_text(session: Session, chapter: Chapter, side: DiffSide) -> str:
    if side.id is None:
        document = chapter.content if isinstance(chapter.content, dict) else empty_document()
        return document_to_text(document)
    version = _require_version(session, chapter.id, side.id)
    return _version_text(version)


def _version_text(version: ChapterVersion) -> str:
    document = version.content_snapshot if isinstance(version.content_snapshot, dict) else {}
    if not isinstance(document, dict) or document.get("type") != "doc":
        return ""
    return document_to_text(document)


def _memory_proposal_ids(session: Session, chapter_id: str, revision: int) -> list[str]:
    rows = session.scalars(
        select(MemoryChangeProposal.id)
        .where(
            MemoryChangeProposal.source_chapter_id == chapter_id,
            MemoryChangeProposal.source_revision == revision,
        )
        .order_by(MemoryChangeProposal.created_at.asc(), MemoryChangeProposal.id.asc())
    )
    return list(rows)


def _commit_version_write(session: Session, *, wrote_chapter: bool) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if wrote_chapter:
            raise RevisionConflict() from None
        return


def _reload_chapter(session: Session, chapter_id: str) -> Chapter:
    session.expire_all()
    saved = catalog_repo.get_chapter(session, chapter_id)
    if saved is None:
        raise NotFound("章节不存在。")
    return saved


def _version_record(row: ChapterVersion) -> ChapterVersionRecord:
    document = row.content_snapshot if isinstance(row.content_snapshot, dict) else empty_document()
    return ChapterVersionRecord(
        id=row.id,
        chapter_id=row.chapter_id,
        revision=row.revision,
        content_format=row.content_format,
        content_format_version=row.content_format_version,
        change_source=row.change_source,
        change_note=row.change_note,
        word_count=word_count(document),
        preview=preview_text(document),
        ai_task_id=row.ai_task_id,
        repair_candidate_id=row.repair_candidate_id,
        created_at=row.created_at,
    )


def _canonical_content(value: object) -> str:
    if isinstance(value, dict):
        return canonical_dump(cast(dict[str, object], value))
    return ""


def _require_novel(session: Session, novel_id: str) -> Novel:
    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    return novel


def _require_volume(session: Session, volume_id: str) -> Volume:
    volume = catalog_repo.get_volume(session, volume_id)
    if volume is None or catalog_repo.get_novel(session, volume.novel_id) is None:
        raise NotFound("卷不存在。")
    return volume


def _require_volume_in_novel(session: Session, novel_id: str, volume_id: str | None) -> None:
    if volume_id is None:
        return
    volume = _require_volume(session, volume_id)
    if volume.novel_id != novel_id:
        raise InvalidReference("卷不属于这本作品。")


def _require_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None or catalog_repo.get_novel(session, chapter.novel_id) is None:
        raise NotFound("章节不存在。")
    return chapter


def _renumber(chapters: list[Chapter], volume_id: str | None) -> None:
    now = _now()
    for index, chapter in enumerate(chapters):
        chapter.sort_order = index
        chapter.volume_id = volume_id
        chapter.updated_at = now


def _next_sort(rows: list[Volume] | list[Chapter]) -> int:
    if not rows:
        return 0
    return max(row.sort_order for row in rows) + 1


def _copy_title(title: str) -> str:
    suffix = " 副本"
    trimmed = title[: 200 - len(suffix)].rstrip()
    return f"{trimmed}{suffix}"


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _shell_ref(chapter: Chapter) -> ShellChapter:
    return ShellChapter(
        id=chapter.id,
        title=chapter.title,
        word_count=chapter.word_count,
        sort_order=chapter.sort_order,
        volume_id=chapter.volume_id,
    )


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
