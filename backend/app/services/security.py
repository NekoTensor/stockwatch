"""Password hashing and JWT issuing.

`bcrypt` is used directly rather than through passlib: passlib's bcrypt backend
has been a recurring source of version-detection breakage, and the direct API is
four lines.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt
from jwt import InvalidTokenError

from app.config import settings

#: bcrypt silently truncates at 72 bytes; rejecting is better than a password
#: that "works" but is not the password the user typed.
MAX_PASSWORD_BYTES = 72

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised for any token that cannot be trusted."""


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database: fail closed rather than 500.
        return False


def _create_token(subject: str | int, token_type: TokenType, lifetime: timedelta) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + lifetime
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def create_access_token(subject: str | int) -> tuple[str, int]:
    return _create_token(subject, "access", timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(subject: str | int) -> tuple[str, int]:
    return _create_token(subject, "refresh", timedelta(days=settings.refresh_token_days))


def decode_token(token: str, expected_type: TokenType) -> int:
    """Return the user id, or raise `TokenError`.

    The `type` claim is checked explicitly: without it a refresh token would be
    accepted as an access token, quietly turning a 30-minute credential into a
    30-day one.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token.")

    subject = payload.get("sub")
    if subject is None:
        raise TokenError("Token has no subject.")

    try:
        return int(subject)
    except (TypeError, ValueError) as exc:
        raise TokenError("Token subject is not a user id.") from exc
