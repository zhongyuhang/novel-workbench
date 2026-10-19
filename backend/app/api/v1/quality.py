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
    IssueStatus,
    NovelStatsResponse,
    QualityCheckRequest,
    QualityCheckResponse,
    QualityIssuePatch,
    QualityIssueResponse,
    RepairAcceptRequest,
    RepairDecisionResponse,
    RepairGenerateRequest,
    RepairListResponse,
    WritingGoalWrite,
)
from app.services import conflicts as conflict_service
from app.services import quality as quality_service
from app.services import quality_issues as issue_service

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


@router.post("/novels/{novel_id}/quality-check", response_model=QualityCheckResponse)
def run_quality_check(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: QualityCheckRequest | None = None,
) -> QualityCheckResponse:
    body = payload if payload is not None else QualityCheckRequest()
    return issue_service.run_quality_check(session, novel_id, body)


@router.get("/novels/{novel_id}/quality-issues", response_model=list[QualityIssueResponse])
def list_quality_issues(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[IssueStatus | None, Query(alias="status")] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    include_closed: Annotated[bool, Query()] = False,
) -> list[QualityIssueResponse]:
    return issue_service.list_quality_issues(
        session,
        novel_id,
        status=status_filter,
        chapter_id=chapter_id,
        include_closed=include_closed,
    )


@router.get("/quality-issues/{issue_id}", response_model=QualityIssueResponse)
def get_quality_issue(
    issue_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> QualityIssueResponse:
    return issue_service.get_quality_issue(session, issue_id)


@router.patch("/quality-issues/{issue_id}", response_model=QualityIssueResponse)
def update_quality_issue(
    issue_id: str,
    payload: QualityIssuePatch,
    session: Annotated[Session, Depends(get_db)],
) -> QualityIssueResponse:
    return issue_service.update_quality_issue_status(session, issue_id, payload.status)


@router.post("/quality-issues/{issue_id}/repairs", response_model=RepairListResponse)
def generate_repairs(
    issue_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: RepairGenerateRequest | None = None,
) -> RepairListResponse:
    body = payload if payload is not None else RepairGenerateRequest()
    return issue_service.generate_repairs(session, issue_id, body)


@router.post("/quality-repairs/{candidate_id}/accept", response_model=RepairDecisionResponse)
def accept_repair(
    candidate_id: str,
    payload: RepairAcceptRequest,
    session: Annotated[Session, Depends(get_db)],
) -> RepairDecisionResponse:
    return issue_service.accept_repair(session, candidate_id, payload)


@router.post("/quality-repairs/{candidate_id}/reject", response_model=RepairDecisionResponse)
def reject_repair(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> RepairDecisionResponse:
    return issue_service.reject_repair(session, candidate_id)
