"""Change detection and the notification rules.

The most important assertions in the whole backend live here: what counts as a
change, and what counts as worth waking somebody up for.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.detection.models import ProductSnapshot, VariantSnapshot
from app.models import Notification, PriceHistory, StockHistory, TrackedProduct, TrackedVariant, User
from app.models.enums import NotificationType, StockStatus
from app.notifications import engine as notifications
from app.services.changes import apply_snapshot
from app.services.security import hash_password


@pytest.fixture
def user(db: Session) -> User:
    user = User(email="a@example.com", hashed_password=hash_password("correct-horse-9"))
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def product(db: Session, user: User) -> TrackedProduct:
    product = TrackedProduct(
        user_id=user.id,
        url="https://shop.example/p/1",
        name="Leather Jacket",
        currency="INR",
        current_price=Decimal("12990.00"),
        lowest_price=Decimal("12990.00"),
        highest_price=Decimal("12990.00"),
        availability=StockStatus.IN_STOCK.value,
    )
    db.add(product)
    db.flush()

    db.add(PriceHistory(tracked_product_id=product.id, price=Decimal("12990.00"), currency="INR"))
    db.add(
        TrackedVariant(
            tracked_product_id=product.id,
            variant_id="M",
            variant_name="M",
            current_stock=StockStatus.OUT_OF_STOCK.value,
            previous_stock=StockStatus.UNKNOWN.value,
            is_watched=True,
        )
    )
    db.commit()
    db.refresh(product)
    return product


def snapshot(price: str | None = None, m_stock: StockStatus = StockStatus.OUT_OF_STOCK) -> ProductSnapshot:
    return ProductSnapshot(
        url="https://shop.example/p/1",
        name="Leather Jacket",
        currency="INR",
        current_price=Decimal(price) if price else None,
        availability=StockStatus.IN_STOCK,
        variants=[VariantSnapshot(id="M", name="M", availability=m_stock)],
    )


# --------------------------------------------------------------- changes ----


def test_price_change_is_recorded_and_reported(db: Session, product: TrackedProduct):
    changes = apply_snapshot(db, product, snapshot("11990.00"))
    db.commit()

    assert changes.price_changed
    assert changes.price_dropped
    assert changes.previous_price == Decimal("12990.00")
    assert product.current_price == Decimal("11990.00")
    assert product.lowest_price == Decimal("11990.00")
    assert db.query(PriceHistory).count() == 2


def test_unchanged_price_is_still_observed(db: Session, product: TrackedProduct):
    """An unchanged price is written to history but is not a change.

    Recording it is what makes "7-day low" and "average" meaningful.
    """
    changes = apply_snapshot(db, product, snapshot("12990.00"))
    db.commit()

    assert not changes.price_changed
    assert db.query(PriceHistory).count() == 2


def test_restock_is_detected_and_logged(db: Session, product: TrackedProduct):
    changes = apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK))
    db.commit()

    assert len(changes.restocked_variants) == 1
    variant = db.query(TrackedVariant).one()
    assert variant.current_stock == StockStatus.IN_STOCK
    assert variant.previous_stock == StockStatus.OUT_OF_STOCK
    assert variant.last_in_stock_at is not None
    assert db.query(StockHistory).count() == 1


def test_unknown_never_overwrites_a_known_state(db: Session, product: TrackedProduct):
    """The single most important rule in the system."""
    changes = apply_snapshot(db, product, snapshot("12990.00", StockStatus.UNKNOWN))
    db.commit()

    variant = db.query(TrackedVariant).one()
    assert variant.current_stock == StockStatus.OUT_OF_STOCK  # unchanged
    assert changes.variant_changes == []
    assert db.query(StockHistory).count() == 0


def test_new_variant_is_added_but_is_not_a_change(db: Session, product: TrackedProduct):
    fresh = snapshot("12990.00")
    fresh.variants.append(VariantSnapshot(id="L", name="L", availability=StockStatus.IN_STOCK))

    changes = apply_snapshot(db, product, fresh)
    db.commit()

    assert {variant.variant_name for variant in product.variants} == {"M", "L"}
    assert changes.variant_changes == []  # nothing to have changed from


def test_variant_matches_on_name_when_the_store_rewrites_ids(db: Session, product: TrackedProduct):
    fresh = snapshot("12990.00")
    fresh.variants = [VariantSnapshot(id="sku-999-new", name="m", availability=StockStatus.IN_STOCK)]

    changes = apply_snapshot(db, product, fresh)
    db.commit()

    assert len(product.variants) == 1  # matched, not duplicated
    assert len(changes.restocked_variants) == 1


# --------------------------------------------------------- notifications ----


def test_restock_notifies_once(db: Session, product: TrackedProduct):
    changes = apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK))
    created = notifications.evaluate(db, changes)
    db.commit()

    assert len(created) == 1
    assert created[0].type == NotificationType.STOCK_AVAILABLE.value

    # Still in stock on the next check: silence.
    again = apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK))
    assert notifications.evaluate(db, again) == []


def test_out_then_in_notifies_again(db: Session, product: TrackedProduct):
    notifications.evaluate(db, apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK)))
    db.commit()

    # Goes out of stock...
    notifications.evaluate(db, apply_snapshot(db, product, snapshot("12990.00", StockStatus.OUT_OF_STOCK)))
    db.commit()

    # ...and comes back. That is a new event and deserves a new alert.
    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK)))
    db.commit()

    assert len(created) == 1
    assert db.query(Notification).count() == 2


def test_price_drop_notifies_once_then_stays_quiet(db: Session, product: TrackedProduct):
    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("11990.00")))
    db.commit()
    assert [n.type for n in created] == [NotificationType.LOWEST_PRICE_REACHED.value]

    # Same price again: no change, no alert.
    assert notifications.evaluate(db, apply_snapshot(db, product, snapshot("11990.00"))) == []


def test_price_bounce_notifies_again(db: Session, product: TrackedProduct):
    """12,990 -> 11,990 -> 12,490 -> 11,990 is two separate drops."""
    notifications.evaluate(db, apply_snapshot(db, product, snapshot("11990.00")))
    db.commit()
    notifications.evaluate(db, apply_snapshot(db, product, snapshot("12490.00")))
    db.commit()

    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("11990.00")))
    db.commit()

    assert len(created) == 1
    assert created[0].price == Decimal("11990.00")


def test_trivial_price_wobble_is_ignored(db: Session, product: TrackedProduct):
    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("12989.50")))
    db.commit()
    assert created == []


def test_target_price_takes_priority(db: Session, product: TrackedProduct):
    product.target_price = Decimal("12000.00")
    db.commit()

    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("11990.00")))
    db.commit()

    assert [n.type for n in created] == [NotificationType.TARGET_PRICE_REACHED.value]


def test_restock_and_drop_become_one_high_priority_alert(db: Session, product: TrackedProduct):
    changes = apply_snapshot(db, product, snapshot("9990.00", StockStatus.IN_STOCK))
    created = notifications.evaluate(db, changes)
    db.commit()

    assert len(created) == 1
    assert created[0].type == NotificationType.COMBINED_STOCK_AND_PRICE.value
    assert created[0].priority == "high"


def test_unwatched_variants_do_not_notify(db: Session, product: TrackedProduct):
    variant = db.query(TrackedVariant).one()
    variant.is_watched = False
    db.commit()

    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK)))
    assert created == []


def test_stock_tracking_can_be_switched_off(db: Session, product: TrackedProduct):
    product.stock_tracking_enabled = False
    db.commit()

    created = notifications.evaluate(db, apply_snapshot(db, product, snapshot("12990.00", StockStatus.IN_STOCK)))
    assert created == []
