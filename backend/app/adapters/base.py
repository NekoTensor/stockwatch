"""The store adapter contract, server side.

Identical philosophy to the extension: **an adapter is an enhancement, never a
requirement.** The generic pipeline runs first and produces a complete snapshot;
an adapter is then handed that snapshot and may fill in the gaps its store is
known to leave.
"""

from __future__ import annotations

from decimal import Decimal

from app.detection.layers import PageContext
from app.detection.models import ProductSnapshot, VariantSnapshot
from app.models.enums import StockStatus


class StoreAdapter:
    """Subclass and override only what your store does *differently*."""

    slug: str = "generic"
    label: str = "Generic"

    #: When true this adapter's fields replace the generic ones instead of only
    #: filling holes. Reserve it for stores known to publish misleading
    #: structured data (a stale JSON-LD price, say).
    authoritative: bool = False

    def can_handle(self, ctx: PageContext) -> bool:
        raise NotImplementedError

    # Every hook below is optional. Returning ``None`` - the common case -
    # means "the generic result is already good enough".

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        return None

    def detect_price(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, Decimal | str | None] | None:
        return None

    def detect_variants(self, ctx: PageContext, base: ProductSnapshot) -> list[VariantSnapshot] | None:
        return None

    def detect_availability(self, ctx: PageContext, base: ProductSnapshot) -> StockStatus | None:
        return None

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return None
