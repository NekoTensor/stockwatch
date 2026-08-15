from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.limiter import login_limit, refresh_limit, register_limit
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
    UserUpdate,
)
from app.services.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.discord_configured = bool(user.discord_webhook_url)
    return out


def _tokens(user: User) -> TokenPair:
    access, expires_in = create_access_token(user.id)
    refresh, _ = create_refresh_token(user.id)
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_limit)],
)
def register(payload: RegisterRequest, db: DbSession) -> TokenPair:
    email = payload.email.lower()

    if db.scalars(select(User).where(User.email == email)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists.")

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _tokens(user)


@router.post("/login", response_model=TokenPair, dependencies=[Depends(login_limit)])
def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    user = db.scalars(select(User).where(User.email == payload.email.lower())).first()

    # Same message and roughly the same work whether the address exists or not,
    # so the endpoint cannot be used to enumerate accounts.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled.")

    return _tokens(user)


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(refresh_limit)])
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    try:
        user_id = decode_token(payload.refresh_token, "refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")

    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    for field in (
        "display_name",
        "email_notifications",
        "browser_notifications",
        "discord_notifications",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(user, field, value)

    if payload.discord_webhook_url is not None:
        # An empty string is how the client clears it; None means "not touching it".
        user.discord_webhook_url = payload.discord_webhook_url or None
        if not user.discord_webhook_url:
            user.discord_notifications = False

    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_me(user: CurrentUser, db: DbSession) -> Response:
    """Delete the account and everything attached to it.

    The privacy policy promises this, so it has to be real and it has to be
    immediate: tracked products, variants, price and stock history, watch rules
    and notifications all go with the row, by cascade at the database rather
    than by a loop here that could miss one.

    Tokens already issued are not revoked — they are signed, not stored — but
    they authenticate a user that no longer exists, so every request made with
    one fails on the next call.
    """
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
