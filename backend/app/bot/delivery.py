"""Which alerts are waiting for a direct message, and marking them sent.

Kept apart from the gateway code so the selection rules can be tested without
a Discord connection — the part that decides who gets told what is the part
worth being sure about.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database.base import utcnow
from app.models import Notification, User

#: Nothing older than this is delivered. A bot that has been down for a day
#: should come back and say what is true now, not replay yesterday into
#: somebody's DMs — and a restock from yesterday is not news anyway.
MAX_AGE = timedelta(hours=6)


def pending_dms(db: Session, limit: int = 50) -> list[Notification]:
    """Alerts destined for a linked Discord account and not yet sent.

    A webhook user is excluded by `discord_sent_at`, which the worker sets
    inline; those never reach here.
    """
    cutoff = utcnow() - MAX_AGE

    query = (
        select(Notification)
        .join(User, Notification.user_id == User.id)
        .where(
            Notification.channel_discord.is_(True),
            Notification.discord_sent_at.is_(None),
            Notification.created_at >= cutoff,
            User.discord_user_id.is_not(None),
            User.discord_notifications.is_(True),
            User.is_active.is_(True),
        )
        .options(
            selectinload(Notification.user),
            selectinload(Notification.product),
            selectinload(Notification.variant),
        )
        .order_by(Notification.created_at.asc())
        .limit(limit)
    )
    return list(db.scalars(query).unique())


def mark_sent(notification: Notification) -> None:
    notification.discord_sent_at = utcnow()
    notification.discord_error = None


def mark_failed(notification: Notification, reason: str) -> None:
    """Record why, and stop trying.

    `discord_sent_at` is set even though nothing was sent: without it the same
    failing alert is retried every poll forever. The error field is what says
    it did not arrive.
    """
    notification.discord_sent_at = utcnow()
    notification.discord_error = reason
