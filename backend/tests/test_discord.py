"""Discord delivery.

The theme, as with email: a failing channel records why and moves on. It never
raises, because raising would roll back the state change that justified the
alert and the user would be told about the same restock again tomorrow.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Notification, Store, TrackedProduct, TrackedVariant, User
from app.models.enums import NotificationType, PriceVerdict
from app.notifications.discord import build_payload, send_notification_discord
from app.services.security import hash_password

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


@pytest.fixture
def notification(db: Session) -> Notification:
    user = User(
        email="d@example.com",
        hashed_password=hash_password("correct-horse-9"),
        discord_notifications=True,
        discord_webhook_url=WEBHOOK,
    )
    db.add(user)
    db.flush()

    store = Store(slug="nike", name="Nike", domain="nike.com")
    db.add(store)
    db.flush()

    product = TrackedProduct(
        user_id=user.id,
        store_id=store.id,
        url="https://www.nike.com/t/air-max-95/CN8490-002",
        name="Air Max 95",
        currency="INR",
        current_price=Decimal("8499.00"),
        image_url="https://static.nike.com/air-max-95.jpg",
    )
    db.add(product)
    db.flush()

    variant = TrackedVariant(
        tracked_product_id=product.id, variant_id="9", variant_name="9", is_watched=True
    )
    db.add(variant)
    db.flush()

    notification = Notification(
        user_id=user.id,
        tracked_product_id=product.id,
        tracked_variant_id=variant.id,
        type=NotificationType.STOCK_AVAILABLE.value,
        priority="high",
        title="Air Max 95 — size 9 is back at ₹8,499",
        message="Size 9 is back in stock. 12% below the 30-day average.",
        price=Decimal("8499.00"),
        previous_price=Decimal("9999.00"),
        currency="INR",
        channel_discord=True,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def test_payload_carries_what_a_reader_needs(notification: Notification):
    payload = build_payload(notification, PriceVerdict.BUY)
    embed = payload["embeds"][0]

    assert embed["title"] == notification.title
    assert embed["url"] == notification.product.url
    assert embed["thumbnail"]["url"] == notification.product.image_url

    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields["Store"] == "Nike"
    assert fields["Size"] == "9"
    # The old price struck through, so the drop is visible at a glance.
    assert "₹8,499" in fields["Price"] and "~~₹9,999~~" in fields["Price"]


def test_the_verdict_colours_the_embed(notification: Notification):
    assert build_payload(notification, PriceVerdict.BUY)["embeds"][0]["color"] == 0x1C7C3C
    assert build_payload(notification, PriceVerdict.HIGH)["embeds"][0]["color"] == 0xC8102E


@respx.mock
def test_successful_post_is_recorded(db: Session, notification: Notification):
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    assert send_notification_discord(notification, PriceVerdict.BUY) is True
    db.commit()

    assert route.called
    assert notification.discord_sent_at is not None
    assert notification.discord_error is None


@respx.mock
def test_a_deleted_webhook_is_recorded_not_raised(db: Session, notification: Notification):
    respx.post(WEBHOOK).mock(return_value=httpx.Response(404))

    assert send_notification_discord(notification) is False
    db.commit()

    assert notification.discord_sent_at is None
    assert "404" in (notification.discord_error or "")


@respx.mock
def test_a_network_failure_is_recorded_not_raised(db: Session, notification: Notification):
    respx.post(WEBHOOK).mock(side_effect=httpx.ConnectError("no route to host"))

    assert send_notification_discord(notification) is False
    db.commit()

    assert notification.discord_sent_at is None
    assert notification.discord_error


def test_no_webhook_means_no_attempt(db: Session, notification: Notification):
    notification.user.discord_webhook_url = None
    db.commit()

    assert send_notification_discord(notification) is False
    assert "No Discord webhook" in (notification.discord_error or "")


def test_disabled_for_the_user_means_no_attempt(db: Session, notification: Notification):
    notification.user.discord_notifications = False
    db.commit()

    assert send_notification_discord(notification) is False
    assert "disabled" in (notification.discord_error or "").lower()


# ------------------------------------------------------------- settings ----


def test_webhook_can_be_set_and_cleared(client: TestClient, auth_headers: dict[str, str]):
    updated = client.patch(
        "/api/auth/me",
        json={"discord_webhook_url": WEBHOOK, "discord_notifications": True},
        headers=auth_headers,
    ).json()
    assert updated["discord_configured"] is True
    assert updated["discord_notifications"] is True
    # The URL is a credential; it must not come back out.
    assert "discord_webhook_url" not in updated

    cleared = client.patch("/api/auth/me", json={"discord_webhook_url": ""}, headers=auth_headers).json()
    assert cleared["discord_configured"] is False
    # Clearing the destination also switches the channel off, so nothing is
    # left "enabled" with nowhere to go.
    assert cleared["discord_notifications"] is False


def test_a_url_that_is_not_a_discord_webhook_is_rejected(client: TestClient, auth_headers: dict[str, str]):
    response = client.patch(
        "/api/auth/me",
        json={"discord_webhook_url": "https://evil.example/collect"},
        headers=auth_headers,
    )
    assert response.status_code == 422
