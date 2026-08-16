"""Engine, session factory and the FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import Settings, settings


def engine_kwargs(config: Settings) -> dict[str, object]:
    """How to connect, given the configuration.

    Separated from `create_engine` so the decisions can be asserted in tests:
    a pool sized for a laptop's own Postgres will exhaust a managed instance's
    connection allowance the moment a second process starts, and that failure
    shows up in production rather than anywhere useful.
    """
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}

    if config.database_url.startswith("sqlite"):
        # Tests run on SQLite; a single connection keeps an in-memory database
        # visible to every session in the process.
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs

    if config.db_disable_pooling:
        # Every checkout opens and closes a real connection. Slower per
        # request, and the right answer behind a transaction-mode pooler.
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = config.db_pool_size
        kwargs["max_overflow"] = config.db_max_overflow
        kwargs["pool_recycle"] = config.db_pool_recycle_seconds

    connect_args: dict[str, object] = {"connect_timeout": config.db_connect_timeout_seconds}
    if config.db_sslmode:
        connect_args["sslmode"] = config.db_sslmode
    kwargs["connect_args"] = connect_args

    return kwargs


def _build_engine() -> Engine:
    return create_engine(settings.database_url, **engine_kwargs(settings))


engine = _build_engine()


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    """SQLite ignores foreign keys unless asked not to.

    Without this the cascade rules the models rely on silently do nothing under
    test, and the tests would pass while production behaved differently.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for Celery tasks and scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
