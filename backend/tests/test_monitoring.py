"""The monitoring loop, with the network mocked.

The theme of this file: every way a check can fail must leave the stored state
alone. A tracker that reports "sold out" because its own request timed out is
worse than one that reports nothing.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from app.models import MonitoringJob, TrackedProduct, TrackedVariant, User
from app.models.enums import CheckStatus, StockStatus
from app.monitoring.engine import check_product, next_check_delay
from app.monitoring.fetcher import fetch_page
from app.services.security import hash_password
from tests.conftest import load_fixture

PRODUCT_URL = "https://www.zara.com/in/en/leather-effect-jacket-p07840321.html"


@pytest.fixture
def product(db: Session) -> TrackedProduct:
    user = User(email="a@example.com", hashed_password=hash_password("correct-horse-9"))
    db.add(user)
    db.flush()

    product = TrackedProduct(
        user_id=user.id,
        url=PRODUCT_URL,
        name="Leather Effect Jacket",
        currency="INR",
        current_price=Decimal("14990.00"),
        lowest_price=Decimal("14990.00"),
        highest_price=Decimal("14990.00"),
        availability=StockStatus.UNKNOWN.value,
    )
    db.add(product)
    db.flush()

    db.add(
        TrackedVariant(
            tracked_product_id=product.id,
            variant_id="M",
            variant_name="M",
            current_stock=StockStatus.IN_STOCK.value,
            previous_stock=StockStatus.UNKNOWN.value,
            is_watched=True,
        )
    )
    db.commit()
    db.refresh(product)
    return product


@respx.mock
def test_successful_check_updates_everything(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(
        return_value=httpx.Response(200, html=load_fixture("jsonld-apparel.html"))
    )

    job = check_product(db, product, send_email=False)
    db.commit()

    assert job.check_status == CheckStatus.OK.value
    assert product.current_price == Decimal("12990.00")  # 14,990 -> 12,990
    assert product.consecutive_failures == 0
    assert product.last_error is None
    assert product.next_check_at is not None

    variant = db.query(TrackedVariant).filter_by(variant_name="M").one()
    assert variant.current_stock == StockStatus.OUT_OF_STOCK  # the fixture has M sold out
    assert variant.previous_stock == StockStatus.IN_STOCK


@respx.mock
def test_timeout_does_not_touch_stock(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    job = check_product(db, product, send_email=False)
    db.commit()

    assert job.check_status == CheckStatus.FAILED.value
    assert product.consecutive_failures == 1
    assert product.last_error
    # Untouched: the failure was ours, not the store's.
    assert product.current_price == Decimal("14990.00")
    assert db.query(TrackedVariant).one().current_stock == StockStatus.IN_STOCK


@respx.mock
def test_rate_limiting_is_recorded_as_blocked_and_backs_off_hard(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(return_value=httpx.Response(429))

    job = check_product(db, product, send_email=False)
    db.commit()

    assert job.check_status == CheckStatus.BLOCKED.value
    assert db.query(TrackedVariant).one().current_stock == StockStatus.IN_STOCK

    blocked = next_check_delay(product, CheckStatus.BLOCKED)
    failed = next_check_delay(product, CheckStatus.FAILED)
    assert blocked > failed


@respx.mock
def test_404_is_not_out_of_stock(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(return_value=httpx.Response(404))

    job = check_product(db, product, send_email=False)
    db.commit()

    assert job.check_status == CheckStatus.NOT_FOUND.value
    assert product.availability == StockStatus.UNKNOWN
    assert db.query(TrackedVariant).one().current_stock == StockStatus.IN_STOCK


@respx.mock
def test_bot_wall_is_partial_not_a_change(db: Session, product: TrackedProduct):
    """A 200 that is not the product page must not be treated as data."""
    respx.get(PRODUCT_URL).mock(
        return_value=httpx.Response(
            200,
            html="<html><body><h1>Enter the characters you see below</h1>"
            + "<p>Sorry, we just need to make sure you're not a robot.</p>" * 5
            + "</body></html>",
        )
    )

    job = check_product(db, product, send_email=False)
    db.commit()

    assert job.check_status == CheckStatus.PARTIAL.value
    assert product.current_price == Decimal("14990.00")
    assert db.query(TrackedVariant).one().current_stock == StockStatus.IN_STOCK


@respx.mock
def test_backoff_grows_with_consecutive_failures(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(return_value=httpx.Response(500))

    first = check_product(db, product, send_email=False)
    db.commit()
    first_delay = product.next_check_at

    check_product(db, product, send_email=False)
    db.commit()

    assert first.check_status == CheckStatus.FAILED.value
    assert product.consecutive_failures == 2
    assert product.next_check_at > first_delay


@respx.mock
def test_recovery_clears_the_failure_count(db: Session, product: TrackedProduct):
    route = respx.get(PRODUCT_URL)
    route.mock(return_value=httpx.Response(500))
    check_product(db, product, send_email=False)
    db.commit()
    assert product.consecutive_failures == 1

    route.mock(return_value=httpx.Response(200, html=load_fixture("jsonld-apparel.html")))
    check_product(db, product, send_email=False)
    db.commit()

    assert product.consecutive_failures == 0
    assert product.last_error is None


@respx.mock
def test_every_check_leaves_an_audit_row(db: Session, product: TrackedProduct):
    respx.get(PRODUCT_URL).mock(return_value=httpx.Response(200, html=load_fixture("jsonld-apparel.html")))

    check_product(db, product, send_email=False)
    db.commit()

    job = db.query(MonitoringJob).one()
    assert job.adapter == "zara"
    assert "jsonld" in (job.layers_used or "")
    assert job.duration_ms is not None


@respx.mock
def test_fetcher_retries_then_succeeds():
    route = respx.get("https://shop.example/p/1")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, html="<html>" + "x" * 300 + "</html>"),
    ]

    result = fetch_page("https://shop.example/p/1", max_retries=2)

    assert result.ok
    assert result.attempts == 2
