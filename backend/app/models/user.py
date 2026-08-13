from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.notification import Notification
    from app.models.product import TrackedProduct


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: Channel preferences. Per-product overrides live on TrackedProduct, and
    #: per-alert overrides on WatchRule; all three must agree for a send.
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    browser_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discord_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: An incoming webhook from the user's own Discord channel settings. Stored
    #: rather than a bot token because it grants exactly one capability: posting
    #: to that one channel.
    discord_webhook_url: Mapped[str | None] = mapped_column(String(512))

    products: Mapped[list[TrackedProduct]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id} {self.email}>"
