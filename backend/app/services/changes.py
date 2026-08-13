"""Change detection: comparing a fresh snapshot to what we already knew.

This module decides *what happened*. It does not decide what to tell the user -
that is `notifications/engine.py` - and it deliberately never writes a state it
is not sure about.

The two rules that everything else follows from:

1. **A failed check is not a change.** If the fetch failed or the page could not
   be parsed, the previous state stands and nothing is recorded.
2. **`UNKNOWN` never overwrites a known state.** A page that stopped exposing
   its size widget has not sold out; it has stopped telling us.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.detection.models import ProductSnapshot
from app.detection.util.text import normalise_key
from app.models import PriceHistory, StockHistory, TrackedProduct, TrackedVariant
from app.models.enums import StockStatus
from app.services.price_stats import refresh_aggregates


@dataclass(slots=True)
class VariantChange:
    variant: TrackedVariant
    previous: StockStatus
    current: StockStatus

    @property
    def came_back_in_stock(self) -> bool:
        return self.previous is StockStatus.OUT_OF_STOCK and self.current is StockStatus.IN_STOCK

    @property
    def went_out_of_stock(self) -> bool:
        return self.previous is StockStatus.IN_STOCK and self.current is StockStatus.OUT_OF_STOCK


@dataclass(slots=True)
class ChangeSet:
    product: TrackedProduct
    price_changed: bool = False
    previous_price: Decimal | None = None
    current_price: Decimal | None = None
    is_new_lowest: bool = False
    target_reached: bool = False
    variant_changes: list[VariantChange] = field(default_factory=list)

    @property
    def price_dropped(self) -> bool:
        return bool(
            self.price_changed
            and self.previous_price is not None
            and self.current_price is not None
            and self.current_price < self.previous_price
        )

    @property
    def price_increased(self) -> bool:
        return bool(
            self.price_changed
            and self.previous_price is not None
            and self.current_price is not None
            and self.current_price > self.previous_price
        )

    @property
    def restocked_variants(self) -> list[VariantChange]:
        return [change for change in self.variant_changes if change.came_back_in_stock]

    @property
    def has_changes(self) -> bool:
        return self.price_changed or bool(self.variant_changes)


def _match_variant(product: TrackedProduct, variant_id: str, name: str) -> TrackedVariant | None:
    """Match on the store's id first, then on a normalised name.

    Stores rewrite their internal ids more often than they rename "M", so the
    name fallback is what keeps a size's history continuous across a redesign.
    """
    for variant in product.variants:
        if variant.variant_id == variant_id:
            return variant
    key = normalise_key(name)
    for variant in product.variants:
        if normalise_key(variant.variant_name) == key:
            return variant
    return None


def apply_snapshot(db: Session, product: TrackedProduct, snapshot: ProductSnapshot) -> ChangeSet:
    """Fold a successful snapshot into the stored state and report the changes."""
    changes = ChangeSet(product=product)

    # --- descriptive fields: keep the best value we have ever seen
    if snapshot.name:
        product.name = snapshot.name
    if snapshot.brand and not product.brand:
        product.brand = snapshot.brand
    if snapshot.image_url:
        product.image_url = snapshot.image_url
    if snapshot.category and not product.category:
        product.category = snapshot.category
    if snapshot.currency:
        product.currency = snapshot.currency
    if snapshot.sku and not product.sku:
        product.sku = snapshot.sku
    if snapshot.product_id and not product.product_id:
        product.product_id = snapshot.product_id
    if snapshot.original_price is not None:
        product.original_price = snapshot.original_price

    # --- price
    if snapshot.current_price is not None:
        previous = product.current_price
        changes.previous_price = previous
        changes.current_price = snapshot.current_price

        # Every observation is recorded, changed or not: that is what makes
        # "7-day low" and "average price" meaningful.
        db.add(
            PriceHistory(
                tracked_product_id=product.id,
                price=snapshot.current_price,
                currency=snapshot.currency or product.currency,
            )
        )
        product.current_price = snapshot.current_price
        changes.price_changed = previous is not None and previous != snapshot.current_price

        previous_lowest = product.lowest_price
        db.flush()
        refresh_aggregates(db, product)

        changes.is_new_lowest = bool(
            previous_lowest is not None
            and product.current_price is not None
            and product.current_price < previous_lowest
        )
        changes.target_reached = bool(
            product.target_price is not None
            and product.current_price is not None
            and product.current_price <= product.target_price
        )

    # --- variants
    seen: set[int] = set()
    for position, incoming in enumerate(snapshot.variants):
        existing = _match_variant(product, incoming.id, incoming.name)

        if existing is None:
            # A size the store has only just started listing. Recorded so it can
            # be watched, but never treated as a "change" - there is no previous
            # state to have changed from.
            existing = TrackedVariant(
                tracked_product_id=product.id,
                variant_id=incoming.id,
                variant_name=incoming.name,
                variant_type=incoming.type,
                sku=incoming.sku,
                price=incoming.price,
                position=position,
                is_watched=False,
                current_stock=incoming.availability,
                previous_stock=StockStatus.UNKNOWN,
            )
            if incoming.availability is StockStatus.IN_STOCK:
                existing.last_in_stock_at = utcnow()
            product.variants.append(existing)
            db.add(existing)
            continue

        seen.add(id(existing))
        existing.position = position
        if incoming.sku:
            existing.sku = incoming.sku
        if incoming.price is not None:
            existing.price = incoming.price

        # Rule 2: unknown never overwrites a known state.
        if incoming.availability is StockStatus.UNKNOWN:
            continue
        if existing.current_stock == incoming.availability:
            continue

        previous = StockStatus(existing.current_stock)
        existing.previous_stock = previous
        existing.current_stock = incoming.availability
        if incoming.availability is StockStatus.IN_STOCK:
            existing.last_in_stock_at = utcnow()

        db.add(
            StockHistory(
                tracked_variant_id=existing.id,
                stock_status=incoming.availability,
                previous_status=previous,
            )
        )
        changes.variant_changes.append(
            VariantChange(variant=existing, previous=previous, current=incoming.availability)
        )

    # --- product-level availability
    #
    # This is the *retailer's* answer - is this product buyable at all - and it
    # is true as soon as any single size is in stock. What the user actually
    # cares about, "can I buy the size I asked about", is derived separately by
    # `TrackedProduct.watched_availability`, and that is what the UI shows.
    if snapshot.availability is not StockStatus.UNKNOWN:
        product.availability = snapshot.availability
    elif product.variants:
        # Derive it rather than leaving a stale value behind.
        known = [v for v in product.variants if v.current_stock != StockStatus.UNKNOWN]
        if known:
            product.availability = (
                StockStatus.IN_STOCK
                if any(v.current_stock == StockStatus.IN_STOCK for v in known)
                else StockStatus.OUT_OF_STOCK
            )

    product.refresh_watched_availability()

    return changes
