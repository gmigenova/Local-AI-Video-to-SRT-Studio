"""SQLAlchemy engine / session management for SQLite (section 7).

- WAL journal mode + foreign keys + busy timeout on every connection.
- Relative SQLite paths resolve against the repository root so the process
  working directory never matters.
- A lazily-initialised global session factory; tests point it at a temp
  database via the ``DATABASE_URL`` environment variable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import REPO_ROOT, get_settings

logger = logging.getLogger(__name__)

_SQLITE_PREFIX = "sqlite:///"


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def resolve_sqlite_url(url: str) -> str:
    """Make a relative sqlite path absolute (repo-root based)."""
    if not url.startswith(_SQLITE_PREFIX):
        return url
    raw = url[len(_SQLITE_PREFIX) :]
    # three-slash form 'sqlite:///relative' -> relative; 'sqlite:////abs' -> abs
    if not raw.startswith("/"):
        path = (REPO_ROOT / raw).resolve()
        return _SQLITE_PREFIX + str(path).replace("\\", "/")
    return url


def make_engine(database_url: str) -> Engine:
    """Create an engine with SQLite pragmas applied (WAL, FKs, busy timeout)."""
    url = resolve_sqlite_url(database_url)
    if url.startswith("sqlite"):
        path = url[len(_SQLITE_PREFIX) :]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    logger.debug("Database engine created for %s", url)
    return engine


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_database(
    database_url: str | None = None, create_tables: bool = False
) -> sessionmaker[Session]:
    """Initialise the global engine + session factory (idempotent)."""
    global _engine, _SessionLocal
    if _SessionLocal is not None and database_url is None:
        return _SessionLocal
    url = database_url or get_settings().database_url
    _engine = make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    if create_tables:
        import app.models  # noqa: F401 - register mappings

        Base.metadata.create_all(_engine)
    return _SessionLocal


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_database()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
