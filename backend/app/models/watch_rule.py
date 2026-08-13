from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import ConditionCombine, PriceCondition, StockCondition

if TYPE_CHECKING:
    from app.models.product import TrackedProduct, TrackedVariant
    from app.models.user import User


class WatchRule(Base, TimestampMixin):
    """A standing question about a product, and where to send the answer.

    The per-product toggles this replaces could only express one thing: "tell me
    about stock and/or price on this product". They could not express "size 9,
    only when it comes back", or "any size, but only under 8,000", or the pair
    of them at once - which is what people actually mean when they track
    something.

    A rule is (what to watch) x (what has to be true) x (where to send it), and
    the monitor becomes a condition evaluator rather than a fixed script.

    Rules are additive: a product with no rules still behaves exactly as before,
    driven by its own price_tracking_enabled / stock_tracking_enabled flags.
    """

    __tablename__ = "watch_rules"
    __table_args__ = (
        Index("ix_watch_rules_product_active", "tracked_product_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    tracked_product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), index=True, nullable=False
    )

    #: Null means "any variant" - the rule is about the product as a whole.
    tracked_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracked_variants.id", ondelete="CASCADE")
    )

    #: Shown in the UI. Generated from the conditions when the user gives none.
    label: Mapped[str | None] = mapped_column(String(160))

    stock_condition: Mapped[str] = mapped_column(String(24), default=StockCondition.ANY, nullable=False)
    price_condition: Mapped[str] = mapped_column(String(24), default=PriceCondition.ANY, nullable=False)
    combine: Mapped[str] = mapped_column(String(8), default=ConditionCombine.ALL, nullable=False)

    #: The threshold for BELOW, in the product's currency.
    price_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    #: The threshold for DROPS_BY_PERCENT and BELOW_AVERAGE.
    percent_value: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    notify_browser: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_discord: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Silence window after firing. Without it a rule phrased as a *state*
    #: ("price is under 8,000") would fire on every single check.
    cooldown_minutes: Mapped[int] = mapped_column(default=720, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_count: Mapped[int] = mapped_column(default=0, nullable=False)

    user: Mapped[User] = relationship()
    product: Mapped[TrackedProduct] = relationship(back_populates="watch_rules")
    variant: Mapped[TrackedVariant | None] = relationship(lazy="joined")

    @property
    def channels(self) -> list[str]:
        selected = []
        if self.notify_browser:
            selected.append("browser")
        if self.notify_email:
            selected.append("email")
        if self.notify_discord:
            selected.append("discord")
        return selected

    def describe(self) -> str:
        """A human label, for when the user did not write one."""
        if self.label:
            return self.label

        parts: list[str] = []
        target = self.variant.variant_name if self.variant else "Any size"

        stock = StockCondition(self.stock_condition)
        if stock is StockCondition.BACK_IN_STOCK:
            parts.append(f"{target} comes back in stock")
        elif stock is StockCondition.IN_STOCK:
            parts.append(f"{target} is in stock")
        elif stock is StockCondition.OUT_OF_STOCK:
            parts.append(f"{target} sells out")

        price = PriceCondition(self.price_condition)
        if price is PriceCondition.BELOW and self.price_value is not None:
            parts.append(f"price is at or below {self.price_value:.0f}")
        elif price is PriceCondition.DROPS_BY_PERCENT and self.percent_value is not None:
            parts.append(f"price drops {self.percent_value:.0f}% or more")
        elif price is PriceCondition.AT_LOWEST:
            parts.append("price hits its lowest recorded")
        elif price is PriceCondition.BELOW_AVERAGE and self.percent_value is not None:
            parts.append(f"price is {self.percent_value:.0f}% below the 30-day average")

        if not parts:
            return "Anything changes"

        joiner = " and " if ConditionCombine(self.combine) is ConditionCombine.ALL else " or "
        return joiner.join(parts).capitalize()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WatchRule {self.id} {self.stock_condition}/{self.price_condition}>"
