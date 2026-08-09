from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.product import TrackedProduct, TrackedVariant


class PriceHistory(Base):
    """One row per *observation*, not per change.

    Keeping unchanged observations is what makes "7-day low" and "average
    price" meaningful — a series that only records changes cannot tell you how
    long a price held.
    """

    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_product_time", "tracked_product_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    product: Mapped[TrackedProduct] = relationship(back_populates="price_history")


class StockHistory(Base):
    """Stock *transitions* only.

    The opposite choice to price history, and for the opposite reason: what
    matters is when a size came back, and writing a row per check would bury
    that in millions of identical rows.
    """

    __tablename__ = "stock_history"
    __table_args__ = (Index("ix_stock_history_variant_time", "tracked_variant_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_variant_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_variants.id", ondelete="CASCADE"), nullable=False
    )
    stock_status: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    variant: Mapped[TrackedVariant] = relationship(back_populates="stock_history")
