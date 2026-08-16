"""How the engine is configured, which differs by where the database lives."""

from __future__ import annotations

from sqlalchemy.pool import NullPool

from app.config import Settings
from app.database.session import engine_kwargs

MANAGED = "postgresql+psycopg://u:p@db.example.com:5432/stockwatch"


def test_sqlite_is_left_alone():
    kwargs = engine_kwargs(Settings(database_url="sqlite+pysqlite:///./x.db"))

    # Pool sizing is meaningless for SQLite and SQLAlchemy rejects it outright.
    assert "pool_size" not in kwargs
    assert kwargs["connect_args"] == {"check_same_thread": False}


def test_a_managed_database_gets_a_small_pool():
    kwargs = engine_kwargs(Settings(database_url=MANAGED))

    # Per process, and there are several processes. The old 10 + 20 exhausted
    # a managed instance's allowance as soon as the worker started.
    assert kwargs["pool_size"] + kwargs["max_overflow"] <= 20
    assert kwargs["pool_pre_ping"] is True


def test_pool_sizes_come_from_configuration():
    kwargs = engine_kwargs(Settings(database_url=MANAGED, db_pool_size=20, db_max_overflow=40))

    assert kwargs["pool_size"] == 20
    assert kwargs["max_overflow"] == 40


def test_ssl_is_requested_when_asked_for():
    plain = engine_kwargs(Settings(database_url=MANAGED))
    secured = engine_kwargs(Settings(database_url=MANAGED, db_sslmode="require"))

    assert "sslmode" not in plain["connect_args"]
    assert secured["connect_args"]["sslmode"] == "require"


def test_connect_timeout_is_always_set():
    """A database that never answers must fail the request, not hang it."""
    kwargs = engine_kwargs(Settings(database_url=MANAGED))

    assert kwargs["connect_args"]["connect_timeout"] > 0


def test_pooling_can_be_handed_to_something_else():
    kwargs = engine_kwargs(Settings(database_url=MANAGED, db_disable_pooling=True))

    assert kwargs["poolclass"] is NullPool
    # Sizing a pool that does not exist is an error, not a no-op.
    assert "pool_size" not in kwargs
