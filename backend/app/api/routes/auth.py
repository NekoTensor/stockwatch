from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.limiter import (
    forgot_password_limit,
    login_limit,
    refresh_limit,
    register_limit,
    verify_email_limit,
)
from app.config import settings
from app.database.base import utcnow
from app.models import User
from app.notifications.email import send_auth_email
from app.schemas.auth import (
    DiscordLinkCodeOut,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserOut,
    UserUpdate,
    VerifyEmailRequest,
)
from app.services import auth_tokens, discord_link
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
    out.discord_linked = bool(user.discord_user_id)
    out.email_verified = user.email_verified_at is not None
    return out


def _tokens(user: User) -> TokenPair:
    access, expires_in = create_access_token(user.id, user.token_version)
    refresh, _ = create_refresh_token(user.id, user.token_version)
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
        claims = decode_token(payload.refresh_token, "refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")

    # A revoked refresh token must not mint a fresh access token; otherwise
    # signing out everywhere lasts until the current access token expires.
    if claims.version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This session has been signed out.")

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


# ------------------------------------------------------------------ discord ----


@router.post("/discord/link-code", response_model=DiscordLinkCodeOut)
def discord_link_code(user: CurrentUser, db: DbSession) -> DiscordLinkCodeOut:
    """Mint a code to type to the bot.

    Issued to a signed-in session and redeemed from inside Discord, so holding
    both ends is what proves the two accounts are the same person. Any code the
    user has not yet used is retired here — two live codes means a mistyped
    first one still works, which is exactly the window worth closing.
    """
    entry = discord_link.issue_code(db, user)
    db.commit()

    return DiscordLinkCodeOut(
        code=entry.code,
        expires_at=entry.expires_at,
        expires_in_minutes=settings.discord_link_code_minutes,
    )


@router.delete("/discord/link", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def discord_unlink(user: CurrentUser, db: DbSession) -> Response:
    """Detach the linked Discord account."""
    discord_link.unlink(db, user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------- recovery ----

#: Always the answer to "forgot password", whether or not the address exists.
#: Confirming which addresses have accounts is a list worth stealing.
FORGOT_REPLY = {"detail": "If that address has an account, a reset code is on its way."}


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(forgot_password_limit)],
)
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> dict[str, str]:
    """Send a reset code, if there is anywhere to send it.

    The same reply either way, and the same rough amount of work, so the
    endpoint cannot be used to find out who has an account.
    """
    user = db.scalars(select(User).where(User.email == payload.email.lower())).first()

    if user is not None and user.is_active:
        code = auth_tokens.issue(db, user, auth_tokens.PASSWORD_RESET)
        db.commit()
        send_auth_email(
            to=user.email,
            subject="Reset your StockWatch password",
            heading="Use this code to set a new password:",
            code=code,
            note=(
                f"It expires in {settings.password_reset_minutes} minutes and can be used once. "
                "If you did not ask for this, nothing has changed and you can ignore it."
            ),
        )

    return FORGOT_REPLY


@router.post("/password/reset", response_model=TokenPair)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> TokenPair:
    """Set a new password with a code from the email.

    Every existing session is dropped. Someone resetting a password is either
    locked out or worried, and in both cases the sessions they cannot see are
    the ones that matter.
    """
    try:
        user = auth_tokens.redeem(db, payload.code, auth_tokens.PASSWORD_RESET)
    except auth_tokens.TokenRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user.hashed_password = hash_password(payload.password)
    user.token_version += 1
    # Redeeming the code proved control of the address, which is the same thing
    # verification asks for.
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    db.commit()
    db.refresh(user)

    return _tokens(user)


@router.post("/logout-all", response_model=TokenPair)
def logout_everywhere(user: CurrentUser, db: DbSession) -> TokenPair:
    """Revoke every session and return a fresh pair for this one."""
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return _tokens(user)


@router.post(
    "/email/verify/request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_email_limit)],
)
def request_email_verification(user: CurrentUser, db: DbSession) -> dict[str, str]:
    if user.email_verified_at is not None:
        return {"detail": "That address is already verified."}

    code = auth_tokens.issue(db, user, auth_tokens.EMAIL_VERIFY)
    db.commit()
    send_auth_email(
        to=user.email,
        subject="Verify your StockWatch email",
        heading="Use this code to verify your email address:",
        code=code,
        note=(
            f"It expires in {settings.email_verify_hours} hours. Verifying is what lets "
            "alerts reach you when your browser is closed."
        ),
    )
    return {"detail": "A verification code is on its way."}


@router.post("/email/verify", response_model=UserOut)
def verify_email(payload: VerifyEmailRequest, user: CurrentUser, db: DbSession) -> UserOut:
    try:
        owner = auth_tokens.redeem(db, payload.code, auth_tokens.EMAIL_VERIFY)
    except auth_tokens.TokenRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # The code belongs to an account, not to whoever is holding the session.
    if owner.id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code belongs to another account.")

    owner.email_verified_at = utcnow()
    db.commit()
    db.refresh(owner)
    return _user_out(owner)
