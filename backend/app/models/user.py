from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.auth_token import AuthToken
    from app.models.discord_link import DiscordLinkCode
    from app.models.notification import Notification
    from app.models.product import TrackedProduct


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: When the address was proven to belong to whoever is using the account.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Bumped to invalidate every token already issued. Access and refresh
    #: tokens are signed rather than stored, so this integer is the only way to
    #: revoke one - on a password change, on sign-out-everywhere, and on any
    #: future "this account was compromised".
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Channel preferences. Per-product overrides live on TrackedProduct, and
    #: per-alert overrides on WatchRule; all three must agree for a send.
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    browser_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discord_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: An incoming webhook from the user's own Discord channel settings. Stored
    #: rather than a bot token because it grants exactly one capability: posting
    #: to that one channel.
    discord_webhook_url: Mapped[str | None] = mapped_column(String(512))
    #: The Discord account this user linked, so the bot can DM them. Set only by
    #: redeeming a link code — see DiscordLinkCode. A webhook posts to a channel
    #: the user owns; this reaches the person wherever they are.
    discord_user_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    products: Mapped[list[TrackedProduct]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    discord_link_codes: Mapped[list[DiscordLinkCode]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    auth_tokens: Mapped[list[AuthToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id} {self.email}>"
