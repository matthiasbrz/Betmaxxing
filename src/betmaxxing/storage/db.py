"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from betmaxxing.config import Settings, get_settings
from betmaxxing.storage.tables import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _configure_sqlite(engine: Engine) -> None:
    """Enable foreign keys and WAL — off by default in SQLite, and both matter."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        url = settings.database_url
        kwargs: dict[str, object] = {"future": True, "echo": False}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            _configure_sqlite(_engine)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(settings), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(settings: Settings | None = None) -> None:
    """Create the schema directly.

    Convenience for tests and first local run. Alembic remains the source of
    truth for a deployed database — see docs/deployment.md.
    """
    Base.metadata.create_all(get_engine(settings))


def reset_engine() -> None:
    """Test hook — drops the cached engine and session factory."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
