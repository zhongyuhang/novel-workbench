"""Liveness and database connectivity."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_db
from app.schemas.health import HealthResponse
from app.services.health import check_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Service health")
def read_health(session: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    status = check_health(session, version=__version__)
    return HealthResponse(
        status="ok",
        service=status.service,
        version=status.version,
        database="ok",
    )
