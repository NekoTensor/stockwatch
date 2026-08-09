from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        """A length floor plus a variety floor.

        Deliberately modest: complexity rules that are too strict push people
        towards `Password1!` everywhere. Length does the real work.
        """
        if value.strip() != value:
            raise ValueError("Password must not start or end with whitespace.")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password must mix letters with numbers or symbols.")
        return value


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


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email_notifications: bool | None = None
    browser_notifications: bool | None = None
