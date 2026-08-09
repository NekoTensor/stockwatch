from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import CheckStatus, StockStatus, VariantType

if TYPE_CHECKING:
    from app.models.history import PriceHistory, StockHistory
    from app.models.store import Store
    from app.models.user import User

#: Money is Numeric, never float. 0.1 + 0.2 problems in a price-drop threshold
#: turn into alerts that fire for a difference that does not exist.
Money = Numeric(12, 2)


class TrackedProduct(Base, TimestampMixin):
    __tablename__ = "tracked_products"
    __table_args__ = (
        # One row per user per product. Re-tracking updates rather than
        # duplicating, which is also what keeps price history continuous.
        UniqueConstraint("user_id", "url", name="uq_tracked_product_user_url"),
        Index("ix_tracked_products_due", "tracking_enabled", "last_checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"), index=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(128), index=True)
    sku: Mapped[str | None] = mapped_column(String(128))

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(255))
    image_url: Mapped[str | None] = mapped_column(Text)

    currency: Mapped[str | None] = mapped_column(String(3))
    current_price: Mapped[Decimal | None] = mapped_column(Money)
    original_price: Mapped[Decimal | None] = mapped_column(Money)
    lowest_price: Mapped[Decimal | None] = mapped_column(Money)
    highest_price: Mapped[Decimal | None] = mapped_column(Money)
    average_price: Mapped[Decimal | None] = mapped_column(Money)

    availability: Mapped[str] = mapped_column(String(20), default=StockStatus.UNKNOWN, nullable=False)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_check_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(default=0, nullable=False)
    #: Set while a store is failing, so the scheduler can back off per product.
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stock_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    target_price: Mapped[Decimal | None] = mapped_column(Money)

    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_browser: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="products")
    store: Mapped[Store | None] = relationship(lazy="joined")
    variants: Mapped[list[TrackedVariant]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrackedVariant.position",
    )
    price_history: Mapped[list[PriceHistory]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def discount_percentage(self) -> int | None:
        if not self.current_price or not self.original_price:
            return None
        if self.original_price <= self.current_price:
            return None
        return int(round((self.original_price - self.current_price) / self.original_price * 100))

    @property
    def is_at_lowest(self) -> bool:
        return bool(self.current_price and self.lowest_price and self.current_price <= self.lowest_price)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TrackedProduct {self.id} {self.name[:40]!r}>"


class TrackedVariant(Base, TimestampMixin):
    """A single buyable option: a size, a shade, a storage tier.

    Stock lives here rather than on the product, because "is it in stock" is
    almost never a question about the product — it is a question about *your*
    size.
    """

    __tablename__ = "tracked_variants"
    __table_args__ = (
        UniqueConstraint("tracked_product_id", "variant_id", name="uq_variant_per_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), index=True, nullable=False
    )

    #: The store's own identifier where there is one, else the label.
    variant_id: Mapped[str] = mapped_column(String(191), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(191), nullable=False)
    variant_type: Mapped[str] = mapped_column(String(20), default=VariantType.GENERIC, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(default=0, nullable=False)

    #: Is the user watching this one? Variants are stored even when unwatched so
    #: the popup can show the full size run without re-detecting.
    is_watched: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    current_stock: Mapped[str] = mapped_column(String(20), default=StockStatus.UNKNOWN, nullable=False)
    previous_stock: Mapped[str] = mapped_column(String(20), default=StockStatus.UNKNOWN, nullable=False)
    last_in_stock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal | None] = mapped_column(Money)

    product: Mapped[TrackedProduct] = relationship(back_populates="variants")
    stock_history: Mapped[list[StockHistory]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TrackedVariant {self.variant_name} {self.current_stock}>"


__all__ = ["CheckStatus", "Money", "TrackedProduct", "TrackedVariant"]
