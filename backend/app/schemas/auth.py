from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel


def check_password_strength(value: str) -> str:
    """A length floor plus a variety floor.

    Deliberately modest: complexity rules that are too strict push people
    towards `Password1!` everywhere. Length does the real work.

    Shared by every path that sets a password. A reset that accepted weaker
    passwords than registration would be a way around the rule rather than a
    second opinion about it.
    """
    if value.strip() != value:
        raise ValueError("Password must not start or end with whitespace.")
    if value.isdigit() or value.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols.")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        return check_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: int
    email: EmailStr
    display_name: str | None
    email_notifications: bool
    browser_notifications: bool
    discord_notifications: bool
    #: Whether one is set, not the URL itself: a webhook is a credential, and
    #: echoing it back to every client that asks is how it ends up in a log.
    discord_configured: bool = False
    #: Whether a Discord account is linked for direct messages. The id itself
    #: is never sent back; only whether there is one.
    discord_linked: bool = False
    #: Whether the address has been proven to belong to whoever uses the account.
    email_verified: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email_notifications: bool | None = None
    browser_notifications: bool | None = None
    discord_notifications: bool | None = None
    #: Empty string clears it.
    discord_webhook_url: str | None = Field(default=None, max_length=512)

    @field_validator("discord_webhook_url")
    @classmethod
    def _looks_like_a_discord_webhook(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not value.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
            raise ValueError("That does not look like a Discord webhook URL.")
        return value


class DiscordLinkCodeOut(BaseModel):
    """A code to type to the bot, and when it stops working."""

    code: str
    expires_at: datetime
    expires_in_minutes: int


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        return check_password_strength(value)


class VerifyEmailRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
