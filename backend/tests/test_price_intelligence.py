"""Price statistics and the buy/wait verdict.

The verdict is the part users act on without reading anything else, so the
tests here are mostly about it refusing to speak when it does not know.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models import PriceHistory, TrackedProduct, User
from app.models.enums import PriceVerdict
from app.services.price_stats import compute_stats
from app.services.security import hash_password


@pytest.fixture
def user(db: Session) -> User:
    user = User(email="p@example.com", hashed_password=hash_password("correct-horse-9"))
    db.add(user)
    db.commit()
    return user


def make_product(db: Session, user: User, current: str, history: list[str], days_apart: int = 2) -> TrackedProduct:
    product = TrackedProduct(
        user_id=user.id,
        url=f"https://shop.example/p/{len(history)}-{current}",
        name="Test Product",
        currency="INR",
        current_price=Decimal(current),
    )
    db.add(product)
    db.flush()

    start = utcnow() - timedelta(days=days_apart * len(history))
    for index, price in enumerate(history):
        db.add(
            PriceHistory(
                tracked_product_id=product.id,
                price=Decimal(price),
                currency="INR",
                recorded_at=start + timedelta(days=days_apart * index),
            )
        )
    db.commit()
    db.refresh(product)
    return product


def test_no_verdict_without_enough_history(db: Session, user: User):
    """Three observations is not a distribution."""
    product = make_product(db, user, "1000", ["1200", "1100", "1000"])
    stats = compute_stats(db, product)

    assert stats.verdict is PriceVerdict.UNKNOWN
    assert "not enough history" in stats.verdict_reason
    assert stats.observations == 3


def test_record_low_is_always_a_buy(db: Session, user: User):
    product = make_product(db, user, "800", ["1200", "1150", "1100", "1000", "800"])
    stats = compute_stats(db, product)

    assert stats.verdict is PriceVerdict.BUY
    assert stats.is_at_lowest is True
    assert "lowest price" in stats.verdict_reason


def test_clearly_below_the_recent_average_is_a_buy(db: Session, user: User):
    product = make_product(db, user, "900", ["1000", "1000", "1000", "1000", "850", "900"])
    stats = compute_stats(db, product)

    assert stats.verdict is PriceVerdict.BUY
    assert stats.vs_average_percentage is not None and stats.vs_average_percentage < 0


def test_clearly_above_the_recent_average_is_high(db: Session, user: User):
    product = make_product(db, user, "1300", ["1000", "1000", "1000", "1000", "1300"])
    stats = compute_stats(db, product)

    assert stats.verdict is PriceVerdict.HIGH
    assert "above the 30-day average" in stats.verdict_reason


def test_a_steady_price_is_fair(db: Session, user: User):
    product = make_product(db, user, "1000", ["1000", "1010", "990", "1000", "1000"])
    stats = compute_stats(db, product)

    assert stats.verdict is PriceVerdict.FAIR


def test_saving_against_the_average_is_money_not_a_percentage(db: Session, user: User):
    product = make_product(db, user, "800", ["1000", "1000", "1000", "1000", "800"])
    stats = compute_stats(db, product)

    assert stats.average_30d == Decimal("960.00")
    assert stats.saving_vs_average == Decimal("160.00")


def test_percentile_reads_low_when_the_price_is_good(db: Session, user: User):
    product = make_product(db, user, "800", ["1200", "1100", "1000", "900", "800"])
    stats = compute_stats(db, product)

    # Cheapest observation in the series: nothing is below it.
    assert stats.percentile == 0


def test_percentile_reads_high_when_the_price_is_bad(db: Session, user: User):
    product = make_product(db, user, "1200", ["1200", "1100", "1000", "900", "800"])
    stats = compute_stats(db, product)

    assert stats.percentile is not None and stats.percentile >= 75


def test_median_resists_a_single_outlier(db: Session, user: User):
    """One freak spike should not move the middle."""
    product = make_product(db, user, "1000", ["1000", "1000", "1000", "1000", "5000"])
    stats = compute_stats(db, product)

    assert stats.median_30d == Decimal("1000.00")
    assert stats.average_30d is not None and stats.average_30d > stats.median_30d


def test_volatility_is_scale_free(db: Session, user: User):
    """Same relative movement on very different price levels scores the same."""
    cheap = make_product(db, user, "100", ["90", "100", "110", "100"])
    dear = make_product(db, user, "90000", ["81000", "90000", "99000", "90000"])

    assert compute_stats(db, cheap).volatility == compute_stats(db, dear).volatility


def test_no_price_at_all_says_so(db: Session, user: User):
    product = make_product(db, user, "1000", [])
    product.current_price = None
    db.commit()

    stats = compute_stats(db, product)
    assert stats.verdict is PriceVerdict.UNKNOWN
    assert stats.observations == 0
