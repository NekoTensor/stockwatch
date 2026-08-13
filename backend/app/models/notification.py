from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utcnow
from app.models.enums import NotificationPriority

if TYPE_CHECKING:
    from app.models.product import TrackedProduct, TrackedVariant
    from app.models.user import User


class Notification(Base):
    """A thing we told the user, and when.

    This table is also the deduplication ledger: "have we already said this?"
    is answered by querying it, not by a cache that disappears on restart.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_time", "user_id", "created_at"),
        Index("ix_notifications_dedupe", "tracked_product_id", "type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tracked_product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), nullable=False
    )
    tracked_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracked_variants.id", ondelete="CASCADE")
    )
    #: The rule that fired, when this alert came from one.
    watch_rule_id: Mapped[int | None] = mapped_column(ForeignKey("watch_rules.id", ondelete="SET NULL"))

    #: Which channels this particular alert is for. A rule can ask for Discord
    #: only; without per-alert channels that intent is lost by the time the
    #: sender runs.
    channel_browser: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channel_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channel_discord: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    type: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default=NotificationPriority.NORMAL, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    #: Snapshot of the numbers at the moment we alerted, so the history reads
    #: correctly even after the product moves on.
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Delivery, tracked per channel so a failed email does not hide the alert
    #: from the browser, or vice versa.
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_error: Mapped[str | None] = mapped_column(Text)
    browser_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discord_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discord_error: Mapped[str | None] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="notifications")
    product: Mapped[TrackedProduct] = relationship(lazy="joined")
    variant: Mapped[TrackedVariant | None] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notification {self.type} product={self.tracked_product_id}>"
