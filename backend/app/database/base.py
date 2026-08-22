"""Declarative base and the columns every table shares."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    `datetime.utcnow()` returns a *naive* datetime, which compares incorrectly
    against the aware values SQLAlchemy loads back from a timezone-aware column.
    Every timestamp in this codebase goes through here.
    """
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Make a timestamp loaded from the database safe to compare in Python.

    Postgres hands back an aware datetime for a timezone-aware column; SQLite,
    which the tests run on, hands back a naive one. Comparing the two raises,
    so anything that reads a stored timestamp and checks it against `utcnow()`
    has to come through here first — the alternative is code that passes its
    tests and raises in production, or the reverse.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
