"""Codes emailed to prove control of an address.

Two uses, one set of rules: issued to one account, valid briefly, redeemable
once. A password reset proves the address still belongs to whoever is asking;
a verification proves it belonged to them in the first place.

A code is emailed rather than a link because there is no website to land on —
the client is a browser extension, so the user pastes the code back into the
popup. That also keeps the credential out of browser history and referrers.

Only the hash is stored. These arrive in an inbox, and a database dump should
not be a list of live password resets.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.base import as_utc, utcnow
from app.models import AuthToken, User

logger = logging.getLogger(__name__)

PASSWORD_RESET = "password_reset"
EMAIL_VERIFY = "email_verify"

#: No I, O, 0 or 1: read out of an email, typed into a popup.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
#: Ten characters of a 32-symbol alphabet is fifty bits — far past guessing
#: within the few minutes a code lives, and still short enough to type.
_LENGTH = 10


class TokenRejected(RuntimeError):
    """Why a code could not be used, in words the user should see."""


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def _lifetime(purpose: str) -> timedelta:
    if purpose == PASSWORD_RESET:
        return timedelta(minutes=settings.password_reset_minutes)
    return timedelta(hours=settings.email_verify_hours)


def issue(db: Session, user: User, purpose: str) -> str:
    """Mint a code and return it. The plaintext is never stored or logged.

    Any unused code for the same purpose is retired first: two live reset codes
    means one the user abandoned still works, which is the window worth closing.
    """
    now = utcnow()
    for stale in db.scalars(
        select(AuthToken).where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
    ):
        stale.expires_at = now

    code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash(code),
            expires_at=now + _lifetime(purpose),
        )
    )
    db.flush()
    logger.info("Issued %s code for user %s", purpose, user.id)
    return code


def redeem(db: Session, code: str, purpose: str) -> User:
    """Consume a code and return whose it was.

    Looked up by hash, so a wrong code and an unknown one take the same path
    and produce the same message — there is nothing here to enumerate.
    """
    entry = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == _hash(code), AuthToken.purpose == purpose
        )
    ).first()

    if entry is None or entry.used_at is not None:
        raise TokenRejected("That code is not valid. Request a new one.")
    if as_utc(entry.expires_at) <= utcnow():
        raise TokenRejected("That code has expired. Request a new one.")

    user = db.get(User, entry.user_id)
    if user is None or not user.is_active:
        raise TokenRejected("That code is not valid. Request a new one.")

    entry.used_at = utcnow()
    db.flush()
    return user
