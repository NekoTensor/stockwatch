from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import NotificationPriority, NotificationType
from app.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: int
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    price: Decimal | None
    previous_price: Decimal | None
    currency: str | None
    created_at: datetime
    read_at: datetime | None
    email_sent_at: datetime | None
    browser_delivered_at: datetime | None

    tracked_product_id: int
    product_name: str | None = None
    product_url: str | None = None
    product_image_url: str | None = None
    variant_name: str | None = None


class MarkReadRequest(BaseModel):
    #: Omit to mark everything read.
    notification_ids: list[int] | None = None


class TestNotificationRequest(BaseModel):
    #: Send against a real tracked product when given, so the email renders
    #: with real content rather than placeholders.
    tracked_product_id: int | None = None
    send_email: bool = True


class UndeliveredOut(BaseModel):
    """What the extension polls for to raise browser notifications."""

    items: list[NotificationOut]
