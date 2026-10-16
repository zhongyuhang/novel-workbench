"""Memory routes. Analysis stores proposals; accept is the only formal write."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.memory import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChapterSummaryResponse,
    EntityCreate,
    EntityResponse,
    EntityUpdate,
    ProposalResponse,
    ProposalStatus,
    ReviewRequest,
    StoryEventResponse,
)
from app.services import memory as memory_service

router = APIRouter(tags=["memory"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/entities", response_model=list[EntityResponse])
def list_entities(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[EntityResponse]:
    return memory_service.list_entities(session, novel_id)


@router.post(
    "/novels/{novel_id}/entities",
    response_model=EntityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_entity(
    novel_id: str,
    payload: EntityCreate,
    session: Annotated[Session, Depends(get_db)],
) -> EntityResponse:
    return memory_service.create_entity(session, novel_id, payload)


@router.patch("/entities/{entity_id}", response_model=EntityResponse)
def update_entity(
    entity_id: str,
    payload: EntityUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> EntityResponse:
    return memory_service.update_entity(session, entity_id, payload)


@router.post("/chapters/{chapter_id}/analyze", response_model=AnalyzeResponse)
def analyze_chapter(
    chapter_id: str,
    payload: AnalyzeRequest,
    session: Annotated[Session, Depends(get_db)],
) -> AnalyzeResponse:
    return memory_service.analyze_chapter(session, chapter_id, payload)


@router.get("/novels/{novel_id}/memory-proposals", response_model=list[ProposalResponse])
def list_memory_proposals(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[ProposalStatus | None, Query(alias="status")] = None,
) -> list[ProposalResponse]:
    return memory_service.list_proposals(session, novel_id, status_filter)


@router.post("/memory-proposals/{proposal_id}/accept", response_model=ProposalResponse)
def accept_memory_proposal(
    proposal_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> ProposalResponse:
    note = payload.review_note if payload is not None else None
    return memory_service.accept_proposal(session, proposal_id, note)


@router.post("/memory-proposals/{proposal_id}/reject", response_model=ProposalResponse)
def reject_memory_proposal(
    proposal_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> ProposalResponse:
    note = payload.review_note if payload is not None else None
    return memory_service.reject_proposal(session, proposal_id, note)


@router.post("/memory-proposals/{proposal_id}/revert", response_model=ProposalResponse)
def revert_memory_proposal(
    proposal_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> ProposalResponse:
    note = payload.review_note if payload is not None else None
    return memory_service.revert_proposal(session, proposal_id, note)


@router.get(
    "/novels/{novel_id}/chapter-summaries",
    response_model=list[ChapterSummaryResponse],
)
def list_chapter_summaries(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[ChapterSummaryResponse]:
    return memory_service.list_chapter_summaries(session, novel_id)


@router.get("/novels/{novel_id}/events", response_model=list[StoryEventResponse])
def list_events(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[StoryEventResponse]:
    return memory_service.list_events(session, novel_id)
