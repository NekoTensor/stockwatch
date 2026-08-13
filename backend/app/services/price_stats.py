"""Price statistics, and the verdict derived from them.

A chart tells you what happened. It does not tell you what to do. The point of
this module is the last few lines of it: turning the series into one of four
words a shopper can act on without reading anything else.
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models import PriceHistory, TrackedProduct
from app.models.enums import PriceVerdict
from app.schemas.product import PriceStats

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}

#: Below this many observations the spread is noise, not a distribution, and a
#: verdict would be dressed-up guesswork.
MIN_OBSERVATIONS_FOR_VERDICT = 4

#: How far under the 30-day average counts as a genuinely good moment.
GOOD_DEAL_DISCOUNT = 5.0
#: And how far over it counts as a bad one.
HIGH_PRICE_PREMIUM = 5.0


def _pct(from_value: Decimal | None, to_value: Decimal | None) -> float | None:
    if not from_value or to_value is None or from_value == 0:
        return None
    return round(float((to_value - from_value) / from_value * 100), 2)


def _decimal(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(float(value), 2)))


def lowest_since(db: Session, product_id: int, days: int) -> Decimal | None:
    since = utcnow() - timedelta(days=days)
    return db.scalar(
        select(func.min(PriceHistory.price)).where(
            PriceHistory.tracked_product_id == product_id,
            PriceHistory.recorded_at >= since,
        )
    )


def prices_since(db: Session, product_id: int, days: int | None) -> list[Decimal]:
    query = select(PriceHistory.price).where(PriceHistory.tracked_product_id == product_id)
    if days is not None:
        query = query.where(PriceHistory.recorded_at >= utcnow() - timedelta(days=days))
    return list(db.scalars(query))


def _percentile_of(current: Decimal | None, series: list[Decimal]) -> int | None:
    """What share of past observations were *cheaper* than the price now.

    0 means nothing has ever been cheaper - this is the best price seen. Low is
    good, which is the opposite of how "percentile" usually reads, so the
    interface presents the complement ("cheaper than 80% of checks") rather
    than this number raw.
    """
    if current is None or len(series) < 2:
        return None
    below = sum(1 for price in series if price < current)
    return int(round(below / len(series) * 100))


def _volatility(series: list[Decimal]) -> float | None:
    """Standard deviation as a percentage of the mean.

    Scale-free on purpose: 200 rupees of movement means something very
    different on a 900 rupee t-shirt than on a 90,000 rupee laptop.
    """
    if len(series) < 3:
        return None
    values = [float(price) for price in series]
    mean = statistics.fmean(values)
    if mean == 0:
        return None
    return round(statistics.pstdev(values) / mean * 100, 2)


def _verdict(
    *,
    current: Decimal | None,
    lowest: Decimal | None,
    average_30d: Decimal | None,
    observations: int,
) -> tuple[PriceVerdict, str]:
    """One word, plus the reason for it.

    The reason is returned alongside because a verdict the user cannot
    interrogate is a verdict they will not trust the second time it is wrong.
    """
    if current is None:
        return PriceVerdict.UNKNOWN, "No price has been recorded yet."

    if observations < MIN_OBSERVATIONS_FOR_VERDICT:
        return (
            PriceVerdict.UNKNOWN,
            f"Only {observations} price {'check' if observations == 1 else 'checks'} so far - "
            "not enough history to judge.",
        )

    if lowest is not None and current <= lowest:
        return PriceVerdict.BUY, "This is the lowest price since you started tracking it."

    if average_30d:
        delta = _pct(average_30d, current)
        if delta is not None:
            if delta <= -GOOD_DEAL_DISCOUNT:
                return PriceVerdict.BUY, f"{abs(delta):.0f}% below the 30-day average."
            if delta >= HIGH_PRICE_PREMIUM:
                return PriceVerdict.HIGH, f"{delta:.0f}% above the 30-day average."
            return PriceVerdict.FAIR, "Within a few percent of the 30-day average."

    return PriceVerdict.FAIR, "Holding steady."


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

    all_prices = prices_since(db, product.id, None)
    prices_30d = prices_since(db, product.id, 30)

    average_30d = _decimal(statistics.fmean(float(p) for p in prices_30d)) if prices_30d else None
    median_30d = _decimal(statistics.median(float(p) for p in prices_30d)) if prices_30d else None
    highest_30d = max(prices_30d) if prices_30d else None

    verdict, reason = _verdict(
        current=product.current_price,
        lowest=lowest,
        average_30d=average_30d,
        observations=int(count or 0),
    )

    # What buying now saves against the recent norm - the number people
    # actually want, rather than a percentage they have to convert.
    saving_vs_average = None
    if product.current_price is not None and average_30d and average_30d > product.current_price:
        saving_vs_average = average_30d - product.current_price

    return PriceStats(
        current=product.current_price,
        previous=previous,
        lowest=lowest,
        highest=highest,
        average=_decimal(average),
        lowest_7d=lowest_since(db, product.id, 7),
        lowest_30d=lowest_since(db, product.id, 30),
        highest_30d=highest_30d,
        average_30d=average_30d,
        median_30d=median_30d,
        change_percentage=_pct(previous, product.current_price),
        below_highest_percentage=_pct(highest, product.current_price),
        vs_average_percentage=_pct(average_30d, product.current_price),
        saving_vs_average=saving_vs_average,
        percentile=_percentile_of(product.current_price, all_prices),
        volatility=_volatility(all_prices),
        observations=int(count or 0),
        is_at_lowest=bool(product.current_price and lowest and product.current_price <= lowest),
        verdict=verdict,
        verdict_reason=reason,
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
    product.average_price = _decimal(average)
