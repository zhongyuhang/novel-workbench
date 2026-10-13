"""Engine and session factory. Callers own transaction boundaries."""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class _DbapiCursor(Protocol):
    def execute(self, statement: str) -> object: ...

    def close(self) -> None: ...


class _DbapiConnection(Protocol):
    def cursor(self) -> _DbapiCursor: ...


def sqlite_connect_args(database_url: str) -> dict[str, object]:
    if not database_url.startswith("sqlite"):
        return {}
    return {"check_same_thread": False, "timeout": 30}


def ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite") or ":memory:" in database_url:
        return
    raw_path = database_url.removeprefix("sqlite:///")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str) -> Engine:
    ensure_sqlite_parent(database_url)
    engine = create_engine(
        database_url,
        connect_args=sqlite_connect_args(database_url),
        pool_pre_ping=True,
    )
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            connection = cast(_DbapiConnection, dbapi_connection)
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
