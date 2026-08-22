"""Application settings.

Everything that differs between a laptop and production lives here and is read
from the environment. No secret is ever committed, and none is ever shipped to
the browser extension — the extension talks to this API and nothing else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: backend/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# The compose deployment passes the environment in directly, so this only
# matters when something is run by hand — and by hand it is usually run from
# backend/, where a bare ".env" resolves to a file that does not exist while
# the real one sits in the repository root. Both are read, the nearer one
# winning, so a local override remains possible.
_ENV_FILES = (_PACKAGE_ROOT.parent / ".env", _PACKAGE_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
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
    #: Connections *per process*, and there are several processes: two uvicorn
    #: workers, a Celery worker and beat. A managed Postgres often allows far
    #: fewer connections than the old 10+20 default multiplied out, so these
    #: default low and are raised deliberately on hardware you control.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800
    db_connect_timeout_seconds: int = 10
    #: Set to "require" (or stricter) for any database reached over the
    #: internet. Providers vary in whether they enforce it server-side.
    db_sslmode: str | None = None
    #: Turn off client-side pooling entirely. Correct when something else is
    #: already pooling — PgBouncer in transaction mode, or a provider's own
    #: pooled endpoint — where holding connections open fights the pooler.
    db_disable_pooling: bool = False

    # --- auth ---
    # Generated per-process when unset so a developer is never silently running
    # on a well-known key; production must set it (see `check_production`).
    secret_key: str = Field(default_factory=lambda: __import__("secrets").token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # --- redis / celery ---
    redis_url: str = "redis://localhost:6379/0"

    # --- rate limiting ---
    rate_limit_enabled: bool = True
    #: In-process by default. With more than one API container a limit of N is
    #: really N per container, so point this at Redis when you scale out.
    rate_limit_storage_uri: str = "memory://"
    #: Registration is slow on purpose: each account is a standing claim on the
    #: monitoring budget, and nobody legitimately needs a second one this hour.
    auth_register_limit: str = "5/hour"
    auth_login_limit: str = "10/minute;100/hour"
    auth_refresh_limit: str = "60/hour"
    #: Whether X-Forwarded-For can be believed. True only when a proxy you
    #: control overwrites it; otherwise a client can forge its own identity.
    trust_proxy_headers: bool = False

    # --- monitoring ---
    #: Check a product the moment it is tracked, instead of leaving it reading
    #: "Not checked yet" until the next sweep. Off in tests, which must not make
    #: network requests.
    check_on_track: bool = True
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

    # --- discord bot ---
    #: The bot's token. Unset means no bot: the API still issues link codes but
    #: nothing is listening to redeem them, so the dashboard hides the option.
    discord_bot_token: str | None = None
    #: How long a link code stays valid. Short on purpose — it is read off one
    #: screen and typed into another, which takes a minute, not a day.
    discord_link_code_minutes: int = 15
    #: How often the bot looks for alerts waiting to be sent as a DM.
    discord_poll_seconds: int = 20
    #: Sync slash commands to this one server as well as globally. Global
    #: commands can take up to an hour to reach clients, which makes testing a
    #: change feel broken; a guild sync is immediate. Set it while developing,
    #: leave it unset in production where the bot serves many servers.
    discord_guild_id: int | None = None

    # --- notifications ---
    resend_api_key: str | None = None
    email_from: str = "StockWatch <alerts@stockwatch.local>"
    #: Follows the API key unless set explicitly — see `_email_follows_the_key`.
    email_enabled: bool = False
    #: Never send the same alert twice within this window, whatever happens.
    notification_cooldown_minutes: int = 60

    # --- cors ---
    # NoDecode matters more than it looks. pydantic-settings treats a complex
    # annotation (list, dict, set) as JSON and decodes it *before* any validator
    # runs, so without this the comma-separated CORS_ORIGINS in .env never
    # reaches the splitter below - it fails as malformed JSON while the process
    # is still starting, and the container crashloops before it can bind a port.
    cors_origins: Annotated[list[str], NoDecode] = [
        "chrome-extension://*",
        "http://localhost:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _email_follows_the_key(self) -> Settings:
        """Configuring a provider is how you say you want email.

        Two switches for one intention is one too many: the deployment that
        went to the trouble of setting RESEND_API_KEY and then never saw an
        email because EMAIL_ENABLED was still false is the whole reason for
        this. An explicit EMAIL_ENABLED still wins, so it stays possible to
        keep the key around with sending switched off.
        """
        if "email_enabled" not in self.model_fields_set and self.resend_api_key:
            self.email_enabled = True
        return self

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
        if self.email_enabled and self.email_from.rstrip(">").endswith(".local"):
            problems.append(
                f"EMAIL_FROM ({self.email_from}) is not a deliverable address; "
                "use a domain verified with your email provider."
            )
        if "sqlite" in self.database_url:
            problems.append("SQLite is not supported in production; use PostgreSQL.")
        return problems

    def production_warnings(self) -> list[str]:
        """Worth saying out loud, not worth refusing to start over."""
        warnings: list[str] = []
        if not self.is_production:
            return warnings

        if not self.email_enabled:
            # Browser and Discord alerts still work, but a restock that happens
            # while Chrome is closed then reaches nobody.
            warnings.append(
                "Email is off (set RESEND_API_KEY to turn it on): alerts will only "
                "reach users while their browser is running."
            )
        if not self.rate_limit_enabled:
            warnings.append("Rate limiting is off: /auth/login is an unlimited password oracle.")
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
