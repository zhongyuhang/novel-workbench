"""Quality routes: foreshadowing, suspected conflicts, and word stats."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.quality import (
    ConflictCheckRequest,
    ConflictCheckResponse,
    ForeshadowingCreate,
    ForeshadowingPatch,
    ForeshadowingResponse,
    ForeshadowingStatus,
    NovelStatsResponse,
    WritingGoalWrite,
)
from app.services import conflicts as conflict_service
from app.services import quality as quality_service

router = APIRouter(tags=["quality"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/foreshadowing", response_model=list[ForeshadowingResponse])
def list_foreshadowing(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[ForeshadowingStatus | None, Query(alias="status")] = None,
) -> list[ForeshadowingResponse]:
    return quality_service.list_foreshadowing(session, novel_id, status_filter)


@router.post(
    "/novels/{novel_id}/foreshadowing",
    response_model=ForeshadowingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_foreshadowing(
    novel_id: str,
    payload: ForeshadowingCreate,
    session: Annotated[Session, Depends(get_db)],
) -> ForeshadowingResponse:
    return quality_service.create_foreshadowing(session, novel_id, payload)


@router.patch("/foreshadowing/{foreshadowing_id}", response_model=ForeshadowingResponse)
def update_foreshadowing(
    foreshadowing_id: str,
    payload: ForeshadowingPatch,
    session: Annotated[Session, Depends(get_db)],
) -> ForeshadowingResponse:
    return quality_service.update_foreshadowing(session, foreshadowing_id, payload)


@router.post("/chapters/{chapter_id}/conflict-check", response_model=ConflictCheckResponse)
def check_conflicts(
    chapter_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ConflictCheckRequest | None = None,
) -> ConflictCheckResponse:
    body = payload if payload is not None else ConflictCheckRequest()
    return conflict_service.check_chapter_conflicts(session, chapter_id, body)


@router.get("/novels/{novel_id}/stats", response_model=NovelStatsResponse)
def get_stats(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> NovelStatsResponse:
    return quality_service.novel_stats(session, novel_id)


@router.put("/novels/{novel_id}/writing-goal", response_model=NovelStatsResponse)
def put_writing_goal(
    novel_id: str,
    payload: WritingGoalWrite,
    session: Annotated[Session, Depends(get_db)],
) -> NovelStatsResponse:
    return quality_service.set_writing_goal(session, novel_id, payload.target_words)
