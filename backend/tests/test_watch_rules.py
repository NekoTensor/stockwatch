"""The watch rule engine.

Two properties matter more than the conditions themselves, and both are about
not crying wolf: a rule phrased as a *state* must not fire on every check, and
nothing may fire on a size we could not read.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.detection.models import ProductSnapshot, VariantSnapshot
from app.models import PriceHistory, TrackedProduct, TrackedVariant, User, WatchRule
from app.models.enums import ConditionCombine, PriceCondition, StockCondition, StockStatus
from app.notifications import engine as notifications
from app.services.changes import apply_snapshot
from app.services.rules import evaluate_rules
from app.services.security import hash_password


@pytest.fixture
def user(db: Session) -> User:
    user = User(email="rules@example.com", hashed_password=hash_password("correct-horse-9"))
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def product(db: Session, user: User) -> TrackedProduct:
    product = TrackedProduct(
        user_id=user.id,
        url="https://shop.example/p/rules",
        name="Air Max 95",
        currency="INR",
        current_price=Decimal("10000.00"),
        lowest_price=Decimal("9000.00"),
        highest_price=Decimal("12000.00"),
        availability=StockStatus.IN_STOCK.value,
    )
    db.add(product)
    db.flush()

    for size, stock in (("8", StockStatus.IN_STOCK), ("9", StockStatus.OUT_OF_STOCK)):
        db.add(
            TrackedVariant(
                tracked_product_id=product.id,
                variant_id=size,
                variant_name=size,
                current_stock=stock.value,
                previous_stock=StockStatus.UNKNOWN.value,
                is_watched=(size == "9"),
            )
        )
    db.add(PriceHistory(tracked_product_id=product.id, price=Decimal("10000.00"), currency="INR"))
    db.commit()
    db.refresh(product)
    return product


def snapshot(price: str, size9: StockStatus, size8: StockStatus = StockStatus.IN_STOCK) -> ProductSnapshot:
    return ProductSnapshot(
        url="https://shop.example/p/rules",
        name="Air Max 95",
        currency="INR",
        current_price=Decimal(price),
        availability=StockStatus.IN_STOCK,
        variants=[
            VariantSnapshot(id="8", name="8", availability=size8),
            VariantSnapshot(id="9", name="9", availability=size9),
        ],
    )


def add_rule(db: Session, product: TrackedProduct, **kwargs) -> WatchRule:
    defaults = {
        "user_id": product.user_id,
        "tracked_product_id": product.id,
        "stock_condition": StockCondition.ANY.value,
        "price_condition": PriceCondition.ANY.value,
        "combine": ConditionCombine.ALL.value,
    }
    rule = WatchRule(**{**defaults, **kwargs})
    db.add(rule)
    db.commit()
    db.refresh(product)
    return rule


def variant_row(db: Session, name: str) -> TrackedVariant:
    return db.query(TrackedVariant).filter_by(variant_name=name).one()


# ------------------------------------------------------------ conditions ----


def test_size_specific_restock_fires_for_that_size(db: Session, product: TrackedProduct):
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
    )

    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.IN_STOCK))
    matches = evaluate_rules(db, product, changes)

    assert len(matches) == 1
    assert matches[0].variant is not None and matches[0].variant.variant_name == "9"
    assert "back in stock" in matches[0].reason


def test_size_specific_rule_ignores_another_size(db: Session, product: TrackedProduct):
    """Size 8 flapping is not news to someone waiting on size 9."""
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
    )
    variant_row(db, "8").current_stock = StockStatus.OUT_OF_STOCK.value
    db.commit()

    changes = apply_snapshot(
        db, product, snapshot("10000.00", StockStatus.OUT_OF_STOCK, size8=StockStatus.IN_STOCK)
    )
    assert evaluate_rules(db, product, changes) == []


def test_price_below_a_threshold_fires(db: Session, product: TrackedProduct):
    add_rule(db, product, price_condition=PriceCondition.BELOW.value, price_value=Decimal("8500"))

    changes = apply_snapshot(db, product, snapshot("7999.00", StockStatus.OUT_OF_STOCK))
    matches = evaluate_rules(db, product, changes)

    assert len(matches) == 1
    assert "at or below" in matches[0].reason


def test_price_above_the_threshold_stays_quiet(db: Session, product: TrackedProduct):
    add_rule(db, product, price_condition=PriceCondition.BELOW.value, price_value=Decimal("8500"))

    changes = apply_snapshot(db, product, snapshot("9500.00", StockStatus.OUT_OF_STOCK))
    assert evaluate_rules(db, product, changes) == []


def test_percentage_drop_is_measured_against_the_last_check(db: Session, product: TrackedProduct):
    add_rule(
        db, product, price_condition=PriceCondition.DROPS_BY_PERCENT.value, percent_value=Decimal("15")
    )

    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))  # -20%
    matches = evaluate_rules(db, product, changes)

    assert len(matches) == 1
    assert "dropped 20%" in matches[0].reason


def test_a_smaller_drop_does_not_reach_the_threshold(db: Session, product: TrackedProduct):
    add_rule(
        db, product, price_condition=PriceCondition.DROPS_BY_PERCENT.value, percent_value=Decimal("15")
    )

    changes = apply_snapshot(db, product, snapshot("9500.00", StockStatus.OUT_OF_STOCK))  # -5%
    assert evaluate_rules(db, product, changes) == []


def test_both_conditions_required_when_combining_with_all(db: Session, product: TrackedProduct):
    """"My size, at my price" - the case the old per-product toggles could not express."""
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
        price_condition=PriceCondition.BELOW.value,
        price_value=Decimal("8500"),
        combine=ConditionCombine.ALL.value,
    )

    # Back in stock, but still too expensive.
    changes = apply_snapshot(db, product, snapshot("9500.00", StockStatus.IN_STOCK))
    assert evaluate_rules(db, product, changes) == []

    # Now cheap enough, and it comes back again.
    apply_snapshot(db, product, snapshot("9500.00", StockStatus.OUT_OF_STOCK))
    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.IN_STOCK))
    matches = evaluate_rules(db, product, changes)

    assert len(matches) == 1
    assert matches[0].stock_met and matches[0].price_met


def test_either_condition_is_enough_when_combining_with_any(db: Session, product: TrackedProduct):
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
        price_condition=PriceCondition.BELOW.value,
        price_value=Decimal("8500"),
        combine=ConditionCombine.ANY.value,
    )

    # Price alone satisfies it, with the size still sold out.
    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))
    assert len(evaluate_rules(db, product, changes)) == 1


# ------------------------------------------------------------- restraint ----


def test_a_state_rule_does_not_fire_on_every_check(db: Session, product: TrackedProduct):
    """"Under 8,500" stays true; it must not say so every hour."""
    rule = add_rule(
        db,
        product,
        price_condition=PriceCondition.BELOW.value,
        price_value=Decimal("8500"),
        cooldown_minutes=720,
    )

    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))
    assert len(evaluate_rules(db, product, changes)) == 1

    rule.last_triggered_at = utcnow()
    db.commit()

    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))
    assert evaluate_rules(db, product, changes) == []


def test_a_state_rule_fires_again_once_the_cooldown_expires(db: Session, product: TrackedProduct):
    rule = add_rule(
        db,
        product,
        price_condition=PriceCondition.BELOW.value,
        price_value=Decimal("8500"),
        cooldown_minutes=60,
    )
    apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))
    rule.last_triggered_at = utcnow() - timedelta(hours=2)
    db.commit()

    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.OUT_OF_STOCK))
    assert len(evaluate_rules(db, product, changes)) == 1


def test_a_transition_rule_needs_no_cooldown(db: Session, product: TrackedProduct):
    """It already fires once, because the transition only happens once."""
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
    )

    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.IN_STOCK))
    assert len(evaluate_rules(db, product, changes)) == 1

    # Still in stock on the next check: nothing transitioned, so nothing fires.
    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.IN_STOCK))
    assert evaluate_rules(db, product, changes) == []


def test_an_unreadable_size_never_triggers_a_restock(db: Session, product: TrackedProduct):
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
    )

    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.UNKNOWN))
    assert evaluate_rules(db, product, changes) == []


def test_an_inactive_rule_is_ignored(db: Session, product: TrackedProduct):
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
        is_active=False,
    )

    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.IN_STOCK))
    assert evaluate_rules(db, product, changes) == []


def test_rules_take_over_from_the_built_in_heuristics(db: Session, product: TrackedProduct):
    """One event, one alert - not one from the rule and one from the defaults."""
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
    )

    changes = apply_snapshot(db, product, snapshot("8000.00", StockStatus.IN_STOCK))
    created = notifications.evaluate(db, changes)
    db.commit()

    assert len(created) == 1
    assert created[0].watch_rule_id is not None


def test_the_alert_carries_the_rule_channels(db: Session, product: TrackedProduct):
    add_rule(
        db,
        product,
        stock_condition=StockCondition.BACK_IN_STOCK.value,
        tracked_variant_id=variant_row(db, "9").id,
        notify_browser=False,
        notify_email=False,
        notify_discord=True,
    )

    changes = apply_snapshot(db, product, snapshot("10000.00", StockStatus.IN_STOCK))
    created = notifications.evaluate(db, changes)
    db.commit()

    assert len(created) == 1
    assert created[0].channel_discord is True
    assert created[0].channel_email is False
    assert created[0].channel_browser is False


# ------------------------------------------------------------------- API ----

RULE_PRODUCT = {
    "url": "https://www.nike.com/t/air-max-95/CN8490-002",
    "name": "Air Max 95",
    "store": "Nike",
    "store_slug": "nike",
    "currency": "INR",
    "current_price": "10000.00",
    "availability": "in_stock",
    "variants": [
        {"id": "8", "name": "8", "type": "size", "availability": "in_stock"},
        {"id": "9", "name": "9", "type": "size", "availability": "out_of_stock"},
    ],
    "watched_variant_ids": ["9"],
}


def test_rule_crud(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=RULE_PRODUCT, headers=auth_headers).json()["id"]

    created = client.post(
        f"/api/products/{product_id}/rules",
        json={
            "variant_id": "9",
            "stock_condition": "back_in_stock",
            "price_condition": "below",
            "price_value": "8500",
            "notify_discord": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["variant_name"] == "9"
    assert "9 comes back in stock" in rule["description"]

    listed = client.get(f"/api/products/{product_id}/rules", headers=auth_headers).json()
    assert len(listed) == 1

    patched = client.patch(
        f"/api/products/{product_id}/rules/{rule['id']}",
        json={"price_value": "7000", "is_active": False},
        headers=auth_headers,
    ).json()
    assert patched["price_value"] == "7000.00"
    assert patched["is_active"] is False

    assert (
        client.delete(f"/api/products/{product_id}/rules/{rule['id']}", headers=auth_headers).status_code
        == 204
    )
    assert client.get(f"/api/products/{product_id}/rules", headers=auth_headers).json() == []


def test_a_rule_with_no_conditions_is_rejected(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=RULE_PRODUCT, headers=auth_headers).json()["id"]

    response = client.post(f"/api/products/{product_id}/rules", json={}, headers=auth_headers)
    assert response.status_code == 422
    assert "at least one condition" in response.text


def test_a_threshold_rule_without_a_threshold_is_rejected(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=RULE_PRODUCT, headers=auth_headers).json()["id"]

    response = client.post(
        f"/api/products/{product_id}/rules",
        json={"price_condition": "below"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_an_unknown_variant_is_rejected(client: TestClient, auth_headers: dict[str, str]):
    """Silently watching every size would be worse than refusing."""
    product_id = client.post("/api/products/track", json=RULE_PRODUCT, headers=auth_headers).json()["id"]

    response = client.post(
        f"/api/products/{product_id}/rules",
        json={"variant_id": "42", "stock_condition": "back_in_stock"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_rules_are_scoped_to_their_owner(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=RULE_PRODUCT, headers=auth_headers).json()["id"]

    other = client.post(
        "/api/auth/register", json={"email": "intruder@example.com", "password": "correct-horse-9"}
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.get(f"/api/products/{product_id}/rules", headers=other_headers).status_code == 404
    assert (
        client.post(
            f"/api/products/{product_id}/rules",
            json={"stock_condition": "back_in_stock"},
            headers=other_headers,
        ).status_code
        == 404
    )
