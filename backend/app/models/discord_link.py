from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class DiscordLinkCode(Base, TimestampMixin):
    """A short-lived proof that a Discord account belongs to a StockWatch user.

    The alternative — asking people to paste their Discord user id — proves
    nothing: ids are public, so anyone could claim anyone's alerts. Here the
    code is issued to a signed-in session and redeemed from inside Discord, so
    holding both ends is the proof.

    Codes are single use and expire quickly; nothing is stored about the
    Discord account until one is redeemed.
    """

    __tablename__ = "discord_link_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set on redemption. Kept rather than deleted so a replayed code can be
    #: told apart from one that never existed.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="discord_link_codes")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DiscordLinkCode {self.code} user={self.user_id}>"
