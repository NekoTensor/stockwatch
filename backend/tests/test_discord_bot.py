"""Account linking and which alerts the bot will send.

The gateway itself is not tested here — that needs Discord. Everything that
decides *who gets told what* is, because that is the part where a mistake sends
someone else's alerts to a stranger.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.bot.delivery import MAX_AGE, mark_failed, mark_sent, pending_dms
from app.database.base import utcnow
from app.models import DiscordLinkCode, Notification, TrackedProduct, User
from app.models.enums import NotificationPriority, NotificationType
from app.services import discord_link
from app.services.security import hash_password


def make_user(db, email="shopper@example.com", **kwargs) -> User:
    # Linking through redeem_code turns the channel on, so a fixture that sets
    # discord_user_id directly has to do the same or it is testing a state the
    # application never produces.
    if kwargs.get("discord_user_id") and "discord_notifications" not in kwargs:
        kwargs["discord_notifications"] = True

    user = User(email=email, hashed_password=hash_password("correct-horse-9"), **kwargs)
    db.add(user)
    db.commit()
    return user


def make_notification(db, user: User, **kwargs) -> Notification:
    product = TrackedProduct(user_id=user.id, url="https://shop.example/p/1", name="Jacket")
    db.add(product)
    db.flush()

    notification = Notification(
        user_id=user.id,
        tracked_product_id=product.id,
        type=NotificationType.STOCK_AVAILABLE,
        priority=NotificationPriority.HIGH,
        title="Back in stock",
        message="Your size is available",
        channel_discord=True,
        **kwargs,
    )
    db.add(notification)
    db.commit()
    return notification


# ---------------------------------------------------------------- linking ----


def test_a_code_links_the_account_that_issued_it(db):
    user = make_user(db)

    code = discord_link.issue_code(db, user)
    db.commit()
    linked = discord_link.redeem_code(db, code.code, "424242424242")
    db.commit()

    assert linked.id == user.id
    assert user.discord_user_id == "424242424242"
    # Linking is an explicit request to be messaged there.
    assert user.discord_notifications is True


def test_a_code_works_exactly_once(db):
    user = make_user(db)
    code = discord_link.issue_code(db, user)
    db.commit()

    discord_link.redeem_code(db, code.code, "111")
    db.commit()

    with pytest.raises(discord_link.LinkError, match="already been used"):
        discord_link.redeem_code(db, code.code, "222")


def test_issuing_a_second_code_retires_the_first(db):
    """A mistyped code must stop working, not linger as a second live one."""
    user = make_user(db)
    first = discord_link.issue_code(db, user)
    db.commit()

    discord_link.issue_code(db, user)
    db.commit()

    with pytest.raises(discord_link.LinkError, match="expired"):
        discord_link.redeem_code(db, first.code, "111")


def test_an_expired_code_is_refused(db):
    user = make_user(db)
    code = discord_link.issue_code(db, user)
    code.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    with pytest.raises(discord_link.LinkError, match="expired"):
        discord_link.redeem_code(db, code.code, "111")


def test_an_unknown_code_is_refused(db):
    with pytest.raises(discord_link.LinkError, match="does not exist"):
        discord_link.redeem_code(db, "ZZZZZZZZ", "111")


def test_one_discord_account_cannot_hold_two_stockwatch_accounts(db):
    """Otherwise linking a taken account silently redirects someone's alerts."""
    first = make_user(db, email="first@example.com")
    second = make_user(db, email="second@example.com")

    discord_link.redeem_code(db, discord_link.issue_code(db, first).code, "999")
    db.commit()

    with pytest.raises(discord_link.LinkError, match="already linked"):
        discord_link.redeem_code(db, discord_link.issue_code(db, second).code, "999")


def test_relinking_the_same_discord_account_is_allowed(db):
    """Unlink then link again is an ordinary thing to do."""
    user = make_user(db)
    discord_link.redeem_code(db, discord_link.issue_code(db, user).code, "999")
    db.commit()

    discord_link.unlink(db, user)
    db.commit()
    assert user.discord_user_id is None
    assert user.discord_notifications is False

    discord_link.redeem_code(db, discord_link.issue_code(db, user).code, "999")
    db.commit()
    assert user.discord_user_id == "999"


def test_unlinking_keeps_the_channel_on_when_a_webhook_remains(db):
    user = make_user(db, discord_webhook_url="https://discord.com/api/webhooks/1/x")
    discord_link.redeem_code(db, discord_link.issue_code(db, user).code, "999")
    db.commit()

    discord_link.unlink(db, user)
    db.commit()

    assert user.discord_user_id is None
    assert user.discord_notifications is True


def test_codes_are_not_guessable_or_ambiguous(db):
    user = make_user(db)
    codes = {discord_link.issue_code(db, user).code for _ in range(20)}

    assert len(codes) == 20
    for code in codes:
        assert len(code) == 8
        # No characters that survive being read off one screen and typed
        # into another only by luck.
        assert not set(code) & set("IO01")


# --------------------------------------------------------------- delivery ----


def test_a_linked_user_with_a_pending_alert_is_collected(db):
    user = make_user(db, discord_user_id="999")
    make_notification(db, user)

    assert len(pending_dms(db)) == 1


def test_an_unlinked_user_is_not(db):
    """Their alerts go by webhook, from the worker, or not at all."""
    user = make_user(db)
    make_notification(db, user)

    assert pending_dms(db) == []


def test_an_already_sent_alert_is_not_resent(db):
    user = make_user(db, discord_user_id="999")
    make_notification(db, user, discord_sent_at=utcnow())

    assert pending_dms(db) == []


def test_a_user_who_turned_discord_off_is_not_messaged(db):
    user = make_user(db, discord_user_id="999", discord_notifications=False)
    make_notification(db, user)

    assert pending_dms(db) == []


def test_stale_alerts_are_left_alone(db):
    """A bot that was down overnight must not replay yesterday into DMs."""
    user = make_user(db, discord_user_id="999")
    old = make_notification(db, user)
    old.created_at = utcnow() - MAX_AGE - timedelta(minutes=1)
    db.commit()

    assert pending_dms(db) == []


def test_a_failure_is_recorded_and_not_retried_forever(db):
    user = make_user(db, discord_user_id="999")
    notification = make_notification(db, user)

    mark_failed(notification, "DMs are closed")
    db.commit()

    assert notification.discord_error == "DMs are closed"
    # Stamped despite failing: otherwise the same alert is retried every poll.
    assert pending_dms(db) == []


def test_success_clears_any_previous_error(db):
    user = make_user(db, discord_user_id="999")
    notification = make_notification(db, user, discord_error="an earlier problem")

    mark_sent(notification)
    db.commit()

    assert notification.discord_sent_at is not None
    assert notification.discord_error is None


# ------------------------------------------------------------------- api ----


def test_the_api_issues_a_code_and_reports_the_link(client, auth_headers, db):
    response = client.post("/api/auth/discord/link-code", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert len(body["code"]) == 8
    assert body["expires_in_minutes"] > 0

    assert client.get("/api/auth/me", headers=auth_headers).json()["discord_linked"] is False

    user = db.scalars(select(User).where(User.email == "shopper@example.com")).first()
    discord_link.redeem_code(db, body["code"], "999")
    db.commit()

    me = client.get("/api/auth/me", headers=auth_headers).json()
    assert me["discord_linked"] is True
    # The id itself is never sent back.
    assert "discord_user_id" not in me
    assert user.discord_user_id == "999"


def test_the_api_unlinks(client, auth_headers, db):
    code = client.post("/api/auth/discord/link-code", headers=auth_headers).json()["code"]
    discord_link.redeem_code(db, code, "999")
    db.commit()

    assert client.delete("/api/auth/discord/link", headers=auth_headers).status_code == 204
    assert client.get("/api/auth/me", headers=auth_headers).json()["discord_linked"] is False


def test_link_codes_die_with_the_account(client, auth_headers, db):
    client.post("/api/auth/discord/link-code", headers=auth_headers)
    assert db.scalars(select(DiscordLinkCode)).first() is not None

    client.delete("/api/auth/me", headers=auth_headers)

    assert db.scalars(select(DiscordLinkCode)).first() is None
