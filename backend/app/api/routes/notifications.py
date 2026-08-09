from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.database.base import utcnow
from app.models import Notification, TrackedProduct
from app.models.enums import NotificationPriority, NotificationType
from app.schemas.common import Message, Page
from app.schemas.notification import (
    MarkReadRequest,
    NotificationOut,
    TestNotificationRequest,
    UndeliveredOut,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(notification: Notification) -> NotificationOut:
    out = NotificationOut.model_validate(notification)
    if notification.product:
        out.product_name = notification.product.name
        out.product_url = notification.product.url
        out.product_image_url = notification.product.image_url
    if notification.variant:
        out.variant_name = notification.variant.variant_name
    return out


@router.get("", response_model=Page[NotificationOut])
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[NotificationOut]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)).unique()

    return Page[NotificationOut](items=[_to_out(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/undelivered", response_model=UndeliveredOut)
def undelivered(user: CurrentUser, db: DbSession) -> UndeliveredOut:
    """Alerts the browser has not shown yet.

    The extension polls this on an alarm and raises a native notification for
    each, then calls `/delivered`. Doing it this way means the browser can be
    closed for a day without losing anything.
    """
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.browser_delivered_at.is_(None),
            Notification.is_test.is_(False),
        )
        .order_by(Notification.created_at.asc())
        .limit(20)
    ).unique()

    return UndeliveredOut(items=[_to_out(row) for row in rows])


@router.post("/delivered", response_model=Message)
def mark_delivered(payload: MarkReadRequest, user: CurrentUser, db: DbSession) -> Message:
    query = select(Notification).where(
        Notification.user_id == user.id, Notification.browser_delivered_at.is_(None)
    )
    if payload.notification_ids:
        query = query.where(Notification.id.in_(payload.notification_ids))

    now = utcnow()
    count = 0
    for notification in db.scalars(query).unique():
        notification.browser_delivered_at = now
        count += 1

    db.commit()
    return Message(detail=f"Marked {count} notification(s) delivered.")


@router.post("/read", response_model=Message)
def mark_read(payload: MarkReadRequest, user: CurrentUser, db: DbSession) -> Message:
    query = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if payload.notification_ids:
        query = query.where(Notification.id.in_(payload.notification_ids))

    now = utcnow()
    count = 0
    for notification in db.scalars(query).unique():
        notification.read_at = now
        count += 1

    db.commit()
    return Message(detail=f"Marked {count} notification(s) read.")


@router.post("/test", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def send_test(payload: TestNotificationRequest, user: CurrentUser, db: DbSession) -> NotificationOut:
    """Prove the pipeline end to end.

    Marked `is_test` so it never participates in deduplication and cannot
    suppress a real alert about the same product.
    """
    if payload.tracked_product_id is not None:
        product = db.scalars(
            select(TrackedProduct).where(
                TrackedProduct.id == payload.tracked_product_id, TrackedProduct.user_id == user.id
            )
        ).first()
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    else:
        product = db.scalars(
            select(TrackedProduct).where(TrackedProduct.user_id == user.id).limit(1)
        ).first()
        if product is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Track a product first - a test alert is rendered from a real one.",
            )

    notification = Notification(
        user_id=user.id,
        tracked_product_id=product.id,
        type=NotificationType.STOCK_AVAILABLE.value,
        priority=NotificationPriority.NORMAL.value,
        title=f"Test alert: {product.name}",
        message="This is a test. Your notification pipeline is working.",
        price=product.current_price,
        currency=product.currency,
        is_test=True,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    if payload.send_email:
        from app.notifications.email import send_notification_email

        send_notification_email(notification)
        db.commit()
        db.refresh(notification)

    return _to_out(notification)
