"""Database connectivity probe."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def ping(session: Session) -> None:
    session.execute(text("SELECT 1"))
