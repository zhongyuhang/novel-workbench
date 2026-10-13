"""Health use case."""

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import DatabaseUnavailable
from app.repositories.health import ping


@dataclass(frozen=True)
class HealthStatus:
    status: str
    service: str
    version: str
    database: str


def check_health(session: Session, *, version: str) -> HealthStatus:
    try:
        ping(session)
    except SQLAlchemyError as exc:
        raise DatabaseUnavailable() from exc
    return HealthStatus(
        status="ok",
        service="ai-novel-writer",
        version=version,
        database="ok",
    )
