"""Price statistics derived from the observation series."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models import PriceHistory, TrackedProduct
from app.schemas.product import PriceStats

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


def _pct(from_value: Decimal | None, to_value: Decimal | None) -> float | None:
    if not from_value or to_value is None or from_value == 0:
        return None
    return round(float((to_value - from_value) / from_value * 100), 2)


def lowest_since(db: Session, product_id: int, days: int) -> Decimal | None:
    since = utcnow() - timedelta(days=days)
    return db.scalar(
        select(func.min(PriceHistory.price)).where(
            PriceHistory.tracked_product_id == product_id,
            PriceHistory.recorded_at >= since,
        )
    )


def compute_stats(db: Session, product: TrackedProduct) -> PriceStats:
    """Everything the dashboard shows about a product's price."""
    row = db.execute(
        select(
            func.min(PriceHistory.price),
            func.max(PriceHistory.price),
            func.avg(PriceHistory.price),
            func.count(PriceHistory.id),
        ).where(PriceHistory.tracked_product_id == product.id)
    ).one()

    lowest, highest, average, count = row

    previous = db.scalar(
        select(PriceHistory.price)
        .where(PriceHistory.tracked_product_id == product.id)
        .order_by(PriceHistory.recorded_at.desc())
        .offset(1)
        .limit(1)
    )

    average_decimal = Decimal(str(round(float(average), 2))) if average is not None and count else None

    return PriceStats(
        current=product.current_price,
        previous=previous,
        lowest=lowest,
        highest=highest,
        average=average_decimal,
        lowest_7d=lowest_since(db, product.id, 7),
        lowest_30d=lowest_since(db, product.id, 30),
        change_percentage=_pct(previous, product.current_price),
        below_highest_percentage=_pct(highest, product.current_price),
        is_at_lowest=bool(product.current_price and lowest and product.current_price <= lowest),
    )


def refresh_aggregates(db: Session, product: TrackedProduct) -> None:
    """Recompute the denormalised min/max/avg kept on the product row.

    They are stored rather than computed on read because the dashboard sorts and
    filters on them, and an aggregate subquery per card does not scale.
    """
    row = db.execute(
        select(func.min(PriceHistory.price), func.max(PriceHistory.price), func.avg(PriceHistory.price))
        .where(PriceHistory.tracked_product_id == product.id)
    ).one()

    lowest, highest, average = row
    product.lowest_price = lowest
    product.highest_price = highest
    product.average_price = Decimal(str(round(float(average), 2))) if average is not None else None
