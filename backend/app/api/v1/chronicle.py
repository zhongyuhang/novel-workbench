"""Chronicle routes. Planning does not write formal events until accept."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.chronicle import (
    ChronicleAccept,
    ChronicleCandidateResponse,
    ChronicleDecisionResponse,
    ChronicleEventPatch,
    ChronicleEventWrite,
    ChroniclePlanRequest,
    ChroniclePlanResponse,
    ChronicleView,
)
from app.schemas.memory import StoryEventResponse
from app.services import chronicle as chronicle_service

router = APIRouter(tags=["chronicle"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/chronicle", response_model=ChronicleView)
def get_chronicle(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChronicleView:
    return chronicle_service.list_chronicle(session, novel_id)


@router.post(
    "/novels/{novel_id}/events",
    response_model=StoryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    novel_id: str,
    payload: ChronicleEventWrite,
    session: Annotated[Session, Depends(get_db)],
) -> StoryEventResponse:
    return chronicle_service.create_event(session, novel_id, payload)


@router.patch("/events/{event_id}", response_model=StoryEventResponse)
def update_event(
    event_id: str,
    payload: ChronicleEventPatch,
    session: Annotated[Session, Depends(get_db)],
) -> StoryEventResponse:
    return chronicle_service.update_event(session, event_id, payload)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    chronicle_service.delete_event(session, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/novels/{novel_id}/chronicle/candidates",
    response_model=list[ChronicleCandidateResponse],
)
def list_chronicle_candidates(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[ChronicleCandidateResponse]:
    return chronicle_service.list_candidates(session, novel_id, status_filter)


@router.post("/novels/{novel_id}/chronicle/plan", response_model=ChroniclePlanResponse)
def plan_chronicle(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ChroniclePlanRequest | None = None,
) -> ChroniclePlanResponse:
    return chronicle_service.plan_events(session, novel_id, payload or ChroniclePlanRequest())


@router.post(
    "/chronicle-candidates/{candidate_id}/accept",
    response_model=ChronicleDecisionResponse,
)
def accept_chronicle_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
    payload: ChronicleAccept | None = None,
) -> ChronicleDecisionResponse:
    return chronicle_service.accept_candidate(
        session,
        candidate_id,
        payload or ChronicleAccept(),
    )


@router.post(
    "/chronicle-candidates/{candidate_id}/reject",
    response_model=ChronicleDecisionResponse,
)
def reject_chronicle_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChronicleDecisionResponse:
    return chronicle_service.reject_candidate(session, candidate_id)


@router.post(
    "/chronicle-candidates/{candidate_id}/defer",
    response_model=ChronicleDecisionResponse,
)
def defer_chronicle_candidate(
    candidate_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChronicleDecisionResponse:
    return chronicle_service.defer_candidate(session, candidate_id)
