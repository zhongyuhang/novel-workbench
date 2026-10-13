"""Local single-user session."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.catalog import SessionRequest, SessionResponse
from app.services.auth import open_local_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", response_model=SessionResponse)
def create_session(
    payload: SessionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    return open_local_session(settings, password=payload.password)
