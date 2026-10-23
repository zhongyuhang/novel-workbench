"""Guided ideation routes. Generating a candidate does not write formal material."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.ideation import (
    IdeationAccept,
    IdeationAnswerCreate,
    IdeationDecisionResponse,
    IdeationGenerateResponse,
    IdeationSessionCreate,
    IdeationSessionResponse,
)
from app.services import ideation as ideation_service

router = APIRouter(tags=["ideation"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/ideation/sessions", response_model=list[IdeationSessionResponse])
def list_ideation_sessions(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[IdeationSessionResponse]:
    return ideation_service.list_sessions(session, novel_id)


@router.post(
    "/novels/{novel_id}/ideation/sessions",
    response_model=IdeationSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ideation_session(
    novel_id: str,
    payload: IdeationSessionCreate,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationSessionResponse:
    return ideation_service.create_session(session, novel_id, payload)


@router.get("/ideation/sessions/{session_id}", response_model=IdeationSessionResponse)
def get_ideation_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationSessionResponse:
    return ideation_service.get_session(session, session_id)


@router.post("/ideation/sessions/{session_id}/answers", response_model=IdeationSessionResponse)
def answer_ideation_session(
    session_id: str,
    payload: IdeationAnswerCreate,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationSessionResponse:
    return ideation_service.answer_session(session, session_id, payload)


@router.post(
    "/ideation/sessions/{session_id}/generate",
    response_model=IdeationGenerateResponse,
)
def generate_ideation_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationGenerateResponse:
    return ideation_service.generate_session(session, session_id)


@router.post(
    "/ideation-candidates/{candidate_id}/accept",
    response_model=IdeationDecisionResponse,
)
def accept_ideation_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: IdeationAccept | None = None,
) -> IdeationDecisionResponse:
    return ideation_service.accept_candidate(session, candidate_id, payload or IdeationAccept())


@router.post(
    "/ideation-candidates/{candidate_id}/reject",
    response_model=IdeationDecisionResponse,
)
def reject_ideation_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationDecisionResponse:
    return ideation_service.reject_candidate(session, candidate_id)


@router.post(
    "/ideation-candidates/{candidate_id}/defer",
    response_model=IdeationDecisionResponse,
)
def defer_ideation_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> IdeationDecisionResponse:
    return ideation_service.defer_candidate(session, candidate_id)
