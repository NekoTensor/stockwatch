from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuthToken(Base, TimestampMixin):
    """A single-use code sent to an email address.

    One table for both purposes because the rules are identical - issued to one
    account, valid briefly, redeemable once - and the purpose is the only thing
    that differs.

    Only a hash is stored. These arrive in an inbox, which is a place that gets
    breached; a database dump should not be a list of live password resets.
    """

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: "password_reset" or "email_verify".
    purpose: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    #: SHA-256 of the code. The code itself exists only in the email.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="auth_tokens")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuthToken {self.purpose} user={self.user_id}>"
