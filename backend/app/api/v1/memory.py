"""Memory routes. Analysis stores proposals; accept is the only formal write."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.memory import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChapterSummaryResponse,
    EntityCreate,
    EntityResponse,
    EntityStateCreate,
    EntityStateResponse,
    EntityStateUpdate,
    EntityUpdate,
    ProposalResponse,
    ProposalStatus,
    RelationResponse,
    RelationStatus,
    RelationUpdate,
    RelationWrite,
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


@router.post(
    "/entities/{entity_id}/states",
    response_model=EntityStateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_entity_state(
    entity_id: str,
    payload: EntityStateCreate,
    session: Annotated[Session, Depends(get_db)],
) -> EntityStateResponse:
    return memory_service.create_entity_state(session, entity_id, payload)


@router.patch("/entity-states/{state_id}", response_model=EntityStateResponse)
def update_entity_state(
    state_id: str,
    payload: EntityStateUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> EntityStateResponse:
    return memory_service.update_entity_state(session, state_id, payload)


@router.delete("/entity-states/{state_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity_state(
    state_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    memory_service.delete_entity_state(session, state_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/novels/{novel_id}/relations", response_model=list[RelationResponse])
def list_relations(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    entity_id: Annotated[str | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[RelationStatus | None, Query(alias="status")] = None,
    storyline: Annotated[str | None, Query()] = None,
) -> list[RelationResponse]:
    return memory_service.list_relations(
        session,
        novel_id,
        entity_id=entity_id,
        chapter_id=chapter_id,
        status=status_filter,
        storyline=storyline,
    )


@router.post(
    "/novels/{novel_id}/relations",
    response_model=RelationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relation(
    novel_id: str,
    payload: RelationWrite,
    session: Annotated[Session, Depends(get_db)],
) -> RelationResponse:
    return memory_service.create_relation(session, novel_id, payload)


@router.patch("/relations/{relation_id}", response_model=RelationResponse)
def update_relation(
    relation_id: str,
    payload: RelationUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> RelationResponse:
    return memory_service.update_relation(session, relation_id, payload)


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(
    relation_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    memory_service.delete_relation(session, relation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
