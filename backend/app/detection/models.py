"""The shape every extraction layer produces.

Deliberately the same vocabulary as the browser extension's `ProductData`, so a
snapshot taken in the popup and one taken by a monitoring worker are directly
comparable. Divergence here would mean the first check after tracking reports
spurious "changes".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import StockStatus, VariantType


@dataclass(slots=True)
class VariantSnapshot:
    id: str
    name: str
    type: VariantType = VariantType.GENERIC
    availability: StockStatus = StockStatus.UNKNOWN
    sku: str | None = None
    price: Decimal | None = None
    source: str = "generic"


@dataclass(slots=True)
class ProductSnapshot:
    """What a page said about a product at one moment."""

    url: str
    store_slug: str = "generic"
    store_name: str = "Unknown Store"
    store_domain: str = ""

    name: str | None = None
    brand: str | None = None
    category: str | None = None
    description: str | None = None

    product_id: str | None = None
    sku: str | None = None
    image_url: str | None = None
    images: list[str] = field(default_factory=list)

    currency: str | None = None
    current_price: Decimal | None = None
    original_price: Decimal | None = None

    availability: StockStatus = StockStatus.UNKNOWN
    variants: list[VariantSnapshot] = field(default_factory=list)

    #: field name -> layer that produced it. Mirrors the extension's provenance
    #: panel and is stored on the monitoring job for post-mortems.
    provenance: dict[str, str] = field(default_factory=dict)
    layers_used: list[str] = field(default_factory=list)
    adapter: str = "generic"
    confidence: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def has_product(self) -> bool:
        """Enough to be worth comparing against the stored state."""
        return bool(self.name) and (self.current_price is not None or bool(self.variants))

    @property
    def discount_percentage(self) -> int | None:
        if not self.current_price or not self.original_price:
            return None
        if self.original_price <= self.current_price:
            return None
        return int(round((self.original_price - self.current_price) / self.original_price * 100))
