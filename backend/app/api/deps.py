"""Shared API dependencies."""

from collections.abc import Iterator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import SessionPrincipal, require_session
from app.db.session import session_scope

__all__ = ["get_db", "require_session", "SessionPrincipal"]


def get_db(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    yield from session_scope(factory)
