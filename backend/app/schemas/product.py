from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.models.enums import StockStatus, VariantType
from app.schemas.common import ORMModel


class VariantIn(BaseModel):
    """A variant as the extension detected it."""

    id: str = Field(max_length=191)
    name: str = Field(max_length=191)
    type: VariantType = VariantType.GENERIC
    availability: StockStatus = StockStatus.UNKNOWN
    sku: str | None = Field(default=None, max_length=128)
    price: Decimal | None = None


class DetectRequest(BaseModel):
    """Server-side detection, for clients that cannot run the extension."""

    url: HttpUrl


class ProductSnapshotOut(BaseModel):
    url: str
    store: str
    store_slug: str
    name: str | None
    brand: str | None
    category: str | None
    product_id: str | None
    sku: str | None
    image_url: str | None
    currency: str | None
    current_price: Decimal | None
    original_price: Decimal | None
    discount_percentage: int | None
    availability: StockStatus
    variants: list[VariantIn]
    confidence: int
    adapter: str
    layers_used: list[str]
    provenance: dict[str, str]
    warnings: list[str]


class TrackRequest(BaseModel):
    """Exactly the payload the extension builds in its popup."""

    url: HttpUrl
    name: str = Field(min_length=1, max_length=512)
    store: str | None = Field(default=None, max_length=160)
    store_slug: str | None = Field(default=None, max_length=64)
    brand: str | None = Field(default=None, max_length=160)
    category: str | None = Field(default=None, max_length=255)
    product_id: str | None = Field(default=None, max_length=128)
    sku: str | None = Field(default=None, max_length=128)
    image_url: str | None = None

    currency: str | None = Field(default=None, max_length=3)
    current_price: Decimal | None = None
    original_price: Decimal | None = None
    availability: StockStatus = StockStatus.UNKNOWN

    variants: list[VariantIn] = Field(default_factory=list)
    #: Which variant ids the user actually wants alerts for. Empty means "the
    #: product as a whole", which is the right behaviour for something with no
    #: variants at all.
    watched_variant_ids: list[str] = Field(default_factory=list)

    price_tracking_enabled: bool = True
    stock_tracking_enabled: bool = True
    target_price: Decimal | None = None
    notify_email: bool = True
    notify_browser: bool = True

    @field_validator("target_price", "current_price", "original_price")
    @classmethod
    def _positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Prices must be greater than zero.")
        return value

    @field_validator("currency")
    @classmethod
    def _iso_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class ProductUpdate(BaseModel):
    tracking_enabled: bool | None = None
    price_tracking_enabled: bool | None = None
    stock_tracking_enabled: bool | None = None
    target_price: Decimal | None = None
    notify_email: bool | None = None
    notify_browser: bool | None = None
    #: Replaces the watched set when provided.
    watched_variant_ids: list[str] | None = None


class VariantOut(ORMModel):
    id: int
    variant_id: str
    variant_name: str
    variant_type: VariantType
    current_stock: StockStatus
    previous_stock: StockStatus
    is_watched: bool
    sku: str | None
    price: Decimal | None
    last_in_stock_at: datetime | None


class PriceStats(BaseModel):
    current: Decimal | None = None
    previous: Decimal | None = None
    lowest: Decimal | None = None
    highest: Decimal | None = None
    average: Decimal | None = None
    lowest_7d: Decimal | None = None
    lowest_30d: Decimal | None = None
    change_percentage: float | None = None
    below_highest_percentage: float | None = None
    is_at_lowest: bool = False


class ProductOut(ORMModel):
    id: int
    url: str
    name: str
    brand: str | None
    category: str | None
    image_url: str | None
    #: Flattened from the Store relationship - the client wants a label, not a
    #: nested object it would have to unwrap on every card.
    store: str | None = None
    store_slug: str | None = None

    @field_validator("store", mode="before")
    @classmethod
    def _flatten_store(cls, value: object) -> object:
        """Accept either a Store row (via `from_attributes`) or a plain string."""
        if value is None or isinstance(value, str):
            return value
        return getattr(value, "name", None)

    currency: str | None
    current_price: Decimal | None
    original_price: Decimal | None
    lowest_price: Decimal | None
    highest_price: Decimal | None
    average_price: Decimal | None
    discount_percentage: int | None = None

    availability: StockStatus
    last_checked_at: datetime | None
    last_check_status: str | None
    consecutive_failures: int

    tracking_enabled: bool
    price_tracking_enabled: bool
    stock_tracking_enabled: bool
    target_price: Decimal | None
    notify_email: bool
    notify_browser: bool

    created_at: datetime
    updated_at: datetime
    variants: list[VariantOut] = Field(default_factory=list)


class ProductDetail(ProductOut):
    price_stats: PriceStats


class PricePoint(BaseModel):
    price: Decimal
    recorded_at: datetime


class PriceHistoryOut(BaseModel):
    product_id: int
    currency: str | None
    range: str
    points: list[PricePoint]
    stats: PriceStats


class StockPoint(BaseModel):
    variant_id: int
    variant_name: str
    stock_status: StockStatus
    previous_status: StockStatus | None
    recorded_at: datetime


class StockHistoryOut(BaseModel):
    product_id: int
    points: list[StockPoint]


class OverviewOut(BaseModel):
    tracked_total: int
    tracking_active: int
    in_stock: int
    out_of_stock: int
    unknown_stock: int
    price_drops_7d: int
    back_in_stock_7d: int
    at_lowest_price: int
    unread_notifications: int
    total_saved: Decimal
    currency: str | None
