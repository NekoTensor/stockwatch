"""Connecting a Discord account to a StockWatch account.

The flow is deliberately one-directional: a signed-in user asks the API for a
code, then types it to the bot from the Discord account they want alerts on.
Holding both ends is the proof, which is why the code is never sent to Discord
by us and never accepted from anywhere but a Discord message.

The obvious shortcut — let people paste their Discord user id into settings —
proves nothing at all. Ids are public; anyone could claim anyone's alerts.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.base import as_utc, utcnow
from app.models import DiscordLinkCode, User

logger = logging.getLogger(__name__)

#: No I, O, 0 or 1: the code gets read off one screen and typed into another.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


class LinkError(RuntimeError):
    """Why a code could not be redeemed, in words a user should see."""


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def issue_code(db: Session, user: User) -> DiscordLinkCode:
    """Mint a fresh code, retiring any the user has not used yet.

    One live code per account: two valid codes means a user who generated a
    second one after mistyping the first still has the first one working,
    which is exactly the window someone shoulder-surfing wants.
    """
    now = utcnow()
    for stale in db.scalars(
        select(DiscordLinkCode).where(
            DiscordLinkCode.user_id == user.id,
            DiscordLinkCode.used_at.is_(None),
            DiscordLinkCode.expires_at > now,
        )
    ):
        stale.expires_at = now

    code = DiscordLinkCode(
        code=_generate_code(),
        user_id=user.id,
        expires_at=now + timedelta(minutes=settings.discord_link_code_minutes),
    )
    db.add(code)
    db.flush()
    return code


def redeem_code(db: Session, code: str, discord_user_id: str) -> User:
    """Attach a Discord account to whoever issued this code.

    Raises LinkError with a message meant for the person who typed it.
    """
    entry = db.scalars(
        select(DiscordLinkCode).where(DiscordLinkCode.code == code.strip().upper())
    ).first()

    if entry is None:
        raise LinkError("That code does not exist. Generate a new one from your StockWatch dashboard.")
    if entry.used_at is not None:
        raise LinkError("That code has already been used. Generate a new one.")
    if as_utc(entry.expires_at) <= utcnow():
        raise LinkError("That code has expired. Generate a new one.")

    # One Discord account per StockWatch account, in both directions: without
    # this, linking a Discord account already attached elsewhere would silently
    # redirect someone else's alerts to it.
    existing = db.scalars(select(User).where(User.discord_user_id == discord_user_id)).first()
    if existing is not None and existing.id != entry.user_id:
        raise LinkError("This Discord account is already linked to another StockWatch account.")

    user = db.get(User, entry.user_id)
    if user is None or not user.is_active:
        raise LinkError("That account is no longer available.")

    user.discord_user_id = discord_user_id
    user.discord_notifications = True
    entry.used_at = utcnow()
    db.flush()

    logger.info("Linked Discord %s to user %s", discord_user_id, user.id)
    return user


def unlink(db: Session, user: User) -> None:
    """Detach the Discord account and stop sending to it."""
    user.discord_user_id = None
    if not user.discord_webhook_url:
        # Nothing left to deliver on, so leaving the channel switched on would
        # only produce alerts that fail.
        user.discord_notifications = False
    db.flush()
