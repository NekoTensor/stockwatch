"""Deciding what to tell the user, and making sure we only say it once.

`services/changes.py` decides *what happened*. This module decides *what is
worth an interruption*, which is a different question: a price that oscillates
by five rupees every hour is a change, and telling anyone about it would be a
bug.

The rules, exactly as specified:

  price      12,990 -> 11,990          notify
             stays at 11,990           silent
             11,990 -> 12,490 -> 11,990  notify again

  stock      out -> in                 notify
             stays in                  silent
             in -> out -> in           notify again

Both are implemented the same way: an alert fires on a *transition*, and the
`notifications` table is the memory of what has already been said. That memory
survives restarts, which a cache would not.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.detection.util.price import quantise
from app.models import Notification, StockHistory, TrackedProduct, TrackedVariant
from app.models.enums import NotificationPriority, NotificationType, StockStatus
from app.services.changes import ChangeSet

logger = logging.getLogger(__name__)

#: A price wobble smaller than this is noise, not news. Applied to the larger
#: of an absolute floor and a percentage, so it works for a 300 rupee t-shirt
#: and a 300,000 rupee laptop alike.
MIN_PRICE_DELTA_PERCENT = Decimal("1.0")
MIN_PRICE_DELTA_ABSOLUTE = Decimal("1.00")


def _format_price(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return "-"
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get((currency or "").upper(), "")
    whole = amount.quantize(Decimal("1")) if amount == amount.to_integral_value() else amount
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency or ''}".strip()


def _recently_sent(
    db: Session,
    product_id: int,
    notification_type: NotificationType,
    *,
    variant_id: int | None = None,
    within_minutes: int | None = None,
) -> Notification | None:
    """The most recent alert of this kind, optionally inside a time window."""
    query = (
        select(Notification)
        .where(
            Notification.tracked_product_id == product_id,
            Notification.type == notification_type.value,
            Notification.is_test.is_(False),
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    if variant_id is not None:
        query = query.where(Notification.tracked_variant_id == variant_id)
    if within_minutes is not None:
        query = query.where(Notification.created_at >= utcnow() - timedelta(minutes=within_minutes))

    return db.scalars(query).first()


def _already_announced_this_restock(db: Session, variant: TrackedVariant) -> bool:
    """Have we already announced *this* return to stock?

    A time window is the wrong tool here: `out -> in -> out -> in` inside an
    hour is two genuine events and must produce two alerts. What actually makes
    an old alert stale is the variant having gone out of stock since. So: find
    the last STOCK_AVAILABLE for this variant, then ask whether the variant has
    been recorded as out of stock at any point after it.
    """
    last = _recently_sent(db, variant.tracked_product_id, NotificationType.STOCK_AVAILABLE, variant_id=variant.id)
    if last is None:
        return False

    # `>=`, not `>`: on Windows the system clock can be coarse enough that two
    # events milliseconds apart share a timestamp to the microsecond, and a
    # strict comparison would then swallow a genuine second restock. The looser
    # bound is safe because this function is only reached on a real OUT -> IN
    # transition, so the variant demonstrably went away at some point.
    went_away_since = db.scalars(
        select(StockHistory.id)
        .where(
            StockHistory.tracked_variant_id == variant.id,
            StockHistory.stock_status == StockStatus.OUT_OF_STOCK.value,
            StockHistory.recorded_at >= last.created_at,
        )
        .limit(1)
    ).first()

    return went_away_since is None


def _price_move_is_material(previous: Decimal | None, current: Decimal | None) -> bool:
    if previous is None or current is None:
        return False
    delta = abs(current - previous)
    if delta < MIN_PRICE_DELTA_ABSOLUTE:
        return False
    if previous == 0:
        return True
    return (delta / previous * 100) >= MIN_PRICE_DELTA_PERCENT


def _already_told_about_this_price(
    db: Session, product: TrackedProduct, notification_type: NotificationType, price: Decimal | None
) -> bool:
    """Have we already announced *this exact price* for this alert type?

    This is what makes "12,990 -> 11,990 -> 11,990 -> 11,990" one notification
    and "12,990 -> 11,990 -> 12,490 -> 11,990" two: the second drop to 11,990 is
    only suppressed if the *last* alert we sent was also for 11,990.
    """
    last = _recently_sent(db, product.id, notification_type)
    if last is None:
        return False
    if last.price is None or price is None:
        return False
    return quantise(last.price) == quantise(price)


def _build(
    product: TrackedProduct,
    notification_type: NotificationType,
    title: str,
    message: str,
    *,
    variant: TrackedVariant | None = None,
    priority: NotificationPriority = NotificationPriority.NORMAL,
    price: Decimal | None = None,
    previous_price: Decimal | None = None,
) -> Notification:
    return Notification(
        user_id=product.user_id,
        tracked_product_id=product.id,
        tracked_variant_id=variant.id if variant else None,
        type=notification_type.value,
        priority=priority.value,
        title=title,
        message=message,
        price=price,
        previous_price=previous_price,
        currency=product.currency,
    )


def evaluate(db: Session, changes: ChangeSet) -> list[Notification]:
    """Turn a change set into the notifications worth sending.

    Nothing is committed here; the caller owns the transaction so that a
    notification and the state change that justified it land together or not
    at all.
    """
    product = changes.product
    created: list[Notification] = []

    price_text = _format_price(changes.current_price, product.currency)
    previous_text = _format_price(changes.previous_price, product.currency)

    def is_new_news(kind: NotificationType) -> bool:
        """Have we not already announced this exact price for this alert type?"""
        return not _already_told_about_this_price(db, product, kind, changes.current_price)

    # --- stock: only variants the user actually asked about
    restocked = [
        change
        for change in changes.restocked_variants
        if change.variant.is_watched and product.stock_tracking_enabled
    ]

    # A restock *and* a price drop in the same check is the moment the user
    # cares most about, so it is one high-priority alert rather than two.
    combined_handled = False
    if restocked and changes.price_dropped and _price_move_is_material(changes.previous_price, changes.current_price):
        names = ", ".join(change.variant.variant_name for change in restocked)
        if is_new_news(NotificationType.COMBINED_STOCK_AND_PRICE):
            created.append(
                _build(
                    product,
                    NotificationType.COMBINED_STOCK_AND_PRICE,
                    f"Back in stock and cheaper: {product.name}",
                    f"{names} is available again, and the price dropped from {previous_text} to {price_text}.",
                    variant=restocked[0].variant,
                    priority=NotificationPriority.HIGH,
                    price=changes.current_price,
                    previous_price=changes.previous_price,
                )
            )
            combined_handled = True

    if not combined_handled:
        for change in restocked:
            variant = change.variant
            if _already_announced_this_restock(db, variant):
                continue

            created.append(
                _build(
                    product,
                    NotificationType.STOCK_AVAILABLE,
                    f"{variant.variant_name} is back in stock",
                    f"{product.name} is available again in {variant.variant_name}"
                    + (f" at {price_text}." if changes.current_price else "."),
                    variant=variant,
                    priority=NotificationPriority.HIGH,
                    price=changes.current_price,
                )
            )

    # --- price
    # When the combined alert fired it has already told the user about the drop;
    # a second price notification for the same event would be a duplicate.
    if product.price_tracking_enabled and changes.price_changed and not combined_handled:
        material = _price_move_is_material(changes.previous_price, changes.current_price)

        if changes.target_reached and product.target_price is not None:
            if is_new_news(NotificationType.TARGET_PRICE_REACHED):
                created.append(
                    _build(
                        product,
                        NotificationType.TARGET_PRICE_REACHED,
                        f"Target price reached: {product.name}",
                        f"Now {price_text}, at or below your target of "
                        f"{_format_price(product.target_price, product.currency)}.",
                        priority=NotificationPriority.HIGH,
                        price=changes.current_price,
                        previous_price=changes.previous_price,
                    )
                )

        elif changes.is_new_lowest and material:
            if is_new_news(NotificationType.LOWEST_PRICE_REACHED):
                created.append(
                    _build(
                        product,
                        NotificationType.LOWEST_PRICE_REACHED,
                        f"Lowest price yet: {product.name}",
                        f"Now {price_text} - the lowest since you started tracking it.",
                        priority=NotificationPriority.HIGH,
                        price=changes.current_price,
                        previous_price=changes.previous_price,
                    )
                )

        elif changes.price_dropped and material:
            if is_new_news(NotificationType.PRICE_DROP):
                created.append(
                    _build(
                        product,
                        NotificationType.PRICE_DROP,
                        f"Price drop: {product.name}",
                        f"Down from {previous_text} to {price_text}.",
                        price=changes.current_price,
                        previous_price=changes.previous_price,
                    )
                )

        # Rises are only sent when the user set a target, i.e. they are waiting
        # to buy and a rise is genuinely actionable. Otherwise it is just noise.
        elif (
            changes.price_increased
            and material
            and product.target_price is not None
            and is_new_news(NotificationType.PRICE_INCREASE)
        ):
            created.append(
                _build(
                    product,
                    NotificationType.PRICE_INCREASE,
                    f"Price went up: {product.name}",
                    f"Up from {previous_text} to {price_text}.",
                    price=changes.current_price,
                    previous_price=changes.previous_price,
                )
            )

    for notification in created:
        db.add(notification)

    if created:
        logger.info(
            "product=%s created %d notification(s): %s",
            product.id,
            len(created),
            ", ".join(n.type for n in created),
        )

    return created
