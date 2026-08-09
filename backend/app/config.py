"""Application settings.

Everything that differs between a laptop and production lives here and is read
from the environment. No secret is ever committed, and none is ever shipped to
the browser extension — the extension talks to this API and nothing else.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_name: str = "StockWatch API"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api"

    # --- database ---
    database_url: str = "postgresql+psycopg://stockwatch:stockwatch@localhost:5432/stockwatch"

    # --- auth ---
    # Generated per-process when unset so a developer is never silently running
    # on a well-known key; production must set it (see `check_production`).
    secret_key: str = Field(default_factory=lambda: __import__("secrets").token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # --- redis / celery ---
    redis_url: str = "redis://localhost:6379/0"

    # --- monitoring ---
    #: Default gap between checks for a tracked product.
    check_interval_minutes: int = 60
    #: A product nobody has opened in a while is checked less often.
    idle_check_interval_minutes: int = 360
    #: Consecutive failures before a product is considered unhealthy.
    max_consecutive_failures: int = 8
    request_timeout_seconds: float = 20.0
    max_retries: int = 3
    #: Minimum seconds between two requests to the same host, across all users.
    per_host_delay_seconds: float = 3.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 StockWatch/1.0 "
        "(+https://github.com/stockwatch)"
    )
    respect_robots_txt: bool = True

    # --- notifications ---
    resend_api_key: str | None = None
    email_from: str = "StockWatch <alerts@stockwatch.local>"
    email_enabled: bool = False
    #: Never send the same alert twice within this window, whatever happens.
    notification_cooldown_minutes: int = 60

    # --- cors ---
    cors_origins: list[str] = ["chrome-extension://*", "http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def check_production(self) -> list[str]:
        """Configuration problems that must not reach production.

        Returned rather than raised so `main` can log every problem at once
        instead of failing on whichever happens to be checked first.
        """
        problems: list[str] = []
        if not self.is_production:
            return problems

        import os

        if not os.getenv("SECRET_KEY"):
            problems.append(
                "SECRET_KEY must be set in production "
                "(a random key would invalidate every session on restart)."
            )
        if self.debug:
            problems.append("DEBUG must be off in production.")
        if self.email_enabled and not self.resend_api_key:
            problems.append("EMAIL_ENABLED is on but RESEND_API_KEY is missing.")
        if "sqlite" in self.database_url:
            problems.append("SQLite is not supported in production; use PostgreSQL.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
