"""Discord delivery, via an incoming webhook.

A webhook rather than a bot: a bot needs an application, a token, an OAuth
install and a gateway connection to do something a single POST already does.
The user pastes a URL from their own channel settings and owns it entirely.

Failures are recorded on the notification and never raised - a Discord outage
must not roll back the state change that produced the alert, or the user would
be told about the same restock again on the next check.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.config import settings
from app.database.base import utcnow
from app.models import Notification
from app.models.enums import PriceVerdict

logger = logging.getLogger(__name__)

#: Discord rejects anything larger, and truncating is friendlier than a 400.
MAX_FIELD = 1024
MAX_TITLE = 256

#: Left border of the embed. Colour is the only styling a webhook really gets.
COLOURS = {
    PriceVerdict.BUY: 0x1C7C3C,      # green: act now
    PriceVerdict.FAIR: 0x767676,     # grey: no strong signal
    PriceVerdict.HIGH: 0xC8102E,     # red: hold off
    PriceVerdict.UNKNOWN: 0x111111,
}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _format_price(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return "—"
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get((currency or "").upper(), "")
    whole = amount.quantize(Decimal("1")) if amount == amount.to_integral_value() else amount
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency or ''}".strip()


def build_payload(notification: Notification, verdict: PriceVerdict = PriceVerdict.UNKNOWN) -> dict:
    """The webhook body: one embed, built to be scannable in a busy channel."""
    product = notification.product

    fields = []
    if product.store:
        fields.append({"name": "Store", "value": _clip(product.store.name, MAX_FIELD), "inline": True})
    if notification.variant:
        fields.append(
            {"name": "Size", "value": _clip(notification.variant.variant_name, MAX_FIELD), "inline": True}
        )

    price_text = _format_price(notification.price or product.current_price, product.currency)
    if notification.previous_price:
        price_text = f"{price_text}  ~~{_format_price(notification.previous_price, product.currency)}~~"
    fields.append({"name": "Price", "value": _clip(price_text, MAX_FIELD), "inline": True})

    embed = {
        "title": _clip(notification.title, MAX_TITLE),
        "description": _clip(notification.message, 4000),
        "url": product.url,
        "color": COLOURS.get(verdict, COLOURS[PriceVerdict.UNKNOWN]),
        "fields": fields,
        "footer": {"text": "StockWatch"},
        "timestamp": notification.created_at.isoformat(),
    }
    if product.image_url:
        embed["thumbnail"] = {"url": product.image_url}

    return {"username": "StockWatch", "embeds": [embed]}


def send_notification_discord(notification: Notification, verdict: PriceVerdict = PriceVerdict.UNKNOWN) -> bool:
    """Post one alert to the user's Discord webhook. Returns whether it went."""
    user = notification.user

    if not user.discord_notifications or not notification.channel_discord:
        notification.discord_error = "Discord disabled for this user or alert."
        return False

    webhook = user.discord_webhook_url
    if not webhook:
        if user.discord_user_id:
            # Bound for a direct message, which needs the gateway connection
            # that only the bot process holds. Left pending deliberately, with
            # no error recorded: the bot picks it up on its next poll, and an
            # error here would look like a failure that never happened.
            return False
        notification.discord_error = "No Discord webhook configured."
        return False

    try:
        response = httpx.post(
            webhook,
            json=build_payload(notification, verdict),
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # 404 means the webhook was deleted; there is no point retrying it.
        notification.discord_error = f"HTTP {exc.response.status_code}"
        logger.warning("Discord rejected notification %s: %s", notification.id, exc.response.status_code)
        return False
    except Exception as exc:  # noqa: BLE001 - provider errors must not escape
        notification.discord_error = f"{type(exc).__name__}: {exc}"
        logger.exception("Failed to post notification %s to Discord", notification.id)
        return False

    notification.discord_sent_at = utcnow()
    notification.discord_error = None
    logger.info("Posted notification %s to Discord", notification.id)
    return True
