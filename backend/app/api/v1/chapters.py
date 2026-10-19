"""Chapter routes."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.catalog import (
    ChapterCreate,
    ChapterMove,
    ChapterResponse,
    ChapterRestore,
    ChapterSummary,
    ChapterVersionDetailResponse,
    ChapterVersionDiffResponse,
    ChapterVersionResponse,
    ChapterWrite,
    TextDiffHunkResponse,
    VersionDiffSide,
)
from app.services import catalog as catalog_service

router = APIRouter(tags=["chapters"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/chapters", response_model=list[ChapterSummary])
def list_chapters(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[ChapterSummary]:
    chapters = catalog_service.list_chapters(session, novel_id)
    return [ChapterSummary.model_validate(chapter) for chapter in chapters]


@router.post(
    "/novels/{novel_id}/chapters",
    response_model=ChapterResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_chapter(
    novel_id: str,
    payload: ChapterCreate,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterResponse:
    chapter = catalog_service.create_chapter(session, novel_id, payload)
    return ChapterResponse.model_validate(chapter)


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
def get_chapter(chapter_id: str, session: Annotated[Session, Depends(get_db)]) -> ChapterResponse:
    return ChapterResponse.model_validate(catalog_service.get_chapter(session, chapter_id))


@router.put("/chapters/{chapter_id}", response_model=ChapterResponse)
def save_chapter(
    chapter_id: str,
    payload: ChapterWrite,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterResponse:
    chapter = catalog_service.save_chapter(session, chapter_id, payload)
    return ChapterResponse.model_validate(chapter)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(chapter_id: str, session: Annotated[Session, Depends(get_db)]) -> Response:
    catalog_service.delete_chapter(session, chapter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/chapters/{chapter_id}/duplicate",
    response_model=ChapterResponse,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_chapter(
    chapter_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterResponse:
    return ChapterResponse.model_validate(catalog_service.duplicate_chapter(session, chapter_id))


@router.get("/chapters/{chapter_id}/versions", response_model=list[ChapterVersionResponse])
def list_chapter_versions(
    chapter_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[ChapterVersionResponse]:
    versions = catalog_service.list_chapter_versions(session, chapter_id)
    return [ChapterVersionResponse.model_validate(version) for version in versions]


@router.get(
    "/chapters/{chapter_id}/versions/diff",
    response_model=ChapterVersionDiffResponse,
)
def diff_chapter_versions(
    chapter_id: str,
    left_id: str,
    right_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterVersionDiffResponse:
    diff = catalog_service.diff_chapter_versions(session, chapter_id, left_id, right_id)
    return ChapterVersionDiffResponse(
        left=VersionDiffSide.model_validate(diff.left),
        right=VersionDiffSide.model_validate(diff.right),
        hunks=[TextDiffHunkResponse(op=_diff_op(hunk.op), text=hunk.text) for hunk in diff.hunks],
    )


@router.get(
    "/chapters/{chapter_id}/versions/{version_id}",
    response_model=ChapterVersionDetailResponse,
)
def get_chapter_version(
    chapter_id: str,
    version_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterVersionDetailResponse:
    detail = catalog_service.get_chapter_version(session, chapter_id, version_id)
    body = ChapterVersionResponse.model_validate(detail.record).model_dump()
    return ChapterVersionDetailResponse(
        **body,
        text=detail.text,
        memory_proposal_ids=list(detail.memory_proposal_ids),
    )


@router.post("/chapters/{chapter_id}/restore", response_model=ChapterResponse)
def restore_chapter(
    chapter_id: str,
    payload: ChapterRestore,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterResponse:
    chapter = catalog_service.restore_chapter(session, chapter_id, payload)
    return ChapterResponse.model_validate(chapter)


@router.post("/chapters/{chapter_id}/move", response_model=ChapterResponse)
def move_chapter(
    chapter_id: str,
    payload: ChapterMove,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterResponse:
    return ChapterResponse.model_validate(
        catalog_service.move_chapter(session, chapter_id, payload)
    )


def _diff_op(value: str) -> Literal["equal", "insert", "delete"]:
    if value in {"equal", "insert", "delete"}:
        return cast("Literal['equal', 'insert', 'delete']", value)
    return "equal"
