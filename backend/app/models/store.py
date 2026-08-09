from __future__ import annotations

from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Store(Base, TimestampMixin):
    """A shop we have seen at least once.

    Rows are created on demand the first time a product from that host is
    tracked, so the table grows to fit whatever the users actually shop on
    rather than a hard-coded list.
    """

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Registry key from the extension ("zara", "myntra", "generic").
    slug: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    default_currency: Mapped[str | None] = mapped_column(String(3))

    #: Politeness controls, per store. A store that starts rate-limiting us can
    #: be slowed down here without touching global settings.
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_request_delay_seconds: Mapped[float | None] = mapped_column(Float)
    check_interval_minutes: Mapped[int | None] = mapped_column()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Store {self.slug} {self.domain}>"
