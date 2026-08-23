"""Request rate limiting.

Only the auth endpoints are limited, and for two different reasons: `/login`
because an unlimited login endpoint is a free password-guessing oracle, and
`/register` because every account created is a standing claim on the monitoring
budget — someone scripting signups costs real money in outbound requests long
after they have gone away.

This wraps `limits` directly rather than using a decorator-based wrapper around
the route: the routes are annotated under `from __future__ import annotations`,
and a wrapper's signature is the one FastAPI reads, which is how request bodies
quietly turn into query parameters. A dependency has no signature to lose.

Counters live in process memory by default, which is enough for one API
container. Running more than one means a limit of N is really N per container,
so set RATE_LIMIT_STORAGE_URI to the Redis instance that is already there.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from limits import RateLimitItem, parse_many
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from app.config import settings

logger = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Who to count this request against.

    Behind a load balancer every request arrives from the balancer, so the
    honest source is the forwarded header — but that header is written by the
    client when nothing trustworthy sits in front, and believing it then would
    let one attacker present as thousands. Hence the setting: opt in only once
    a proxy you control is guaranteed to overwrite it.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

    client = request.client
    return client.host if client else "unknown"


class Limiter:
    """The shared counter store.

    `enabled` is an attribute rather than a check against settings so that tests
    can turn limiting on for one case without the whole suite tripping over the
    counters the previous test left behind.
    """

    def __init__(self, storage_uri: str, *, enabled: bool) -> None:
        self.storage = storage_from_string(storage_uri)
        # A moving window, not a fixed one: fixed windows let twice the limit
        # through across a boundary, which is exactly when a script is trying.
        self.strategy = MovingWindowRateLimiter(self.storage)
        self.enabled = enabled

    def reset(self) -> None:
        self.storage.reset()

    def hit(self, item: RateLimitItem, *identifiers: str) -> bool:
        return self.strategy.hit(item, *identifiers)

    def retry_after(self, item: RateLimitItem, *identifiers: str) -> int:
        """Whole seconds until this window has room again, at least one."""
        stats = self.strategy.get_window_stats(item, *identifiers)
        return max(1, math.ceil(stats.reset_time - time.time()))


limiter = Limiter(settings.rate_limit_storage_uri, enabled=settings.rate_limit_enabled)


def rate_limit(scope: str, limits: str) -> Callable[[Request], None]:
    """Build a dependency that counts calls to one endpoint.

    A closure rather than a callable class: this module annotates under
    `from __future__ import annotations`, and FastAPI resolves an annotation
    against the callable's `__globals__` — which a class instance does not
    have, so `request: Request` would be read as an unresolvable name and
    demoted to a query parameter.

    Used as `dependencies=[Depends(...)]`, so it never appears in the route's
    own signature and cannot disturb how the body is read either.
    """
    # Parsed once at import: a malformed limit string is a startup failure, not
    # a surprise on the first request.
    items = parse_many(limits)

    def dependency(request: Request) -> None:
        if not limiter.enabled:
            return

        key = client_key(request)
        for item in items:
            if limiter.hit(item, scope, key):
                continue

            retry_after = limiter.retry_after(item, scope, key)
            logger.info("Rate limited %s on %s (%s)", key, scope, item)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                # The extension renders `detail`; anything else would surface
                # to the user as a bare "Request failed (429)".
                detail=f"Too many attempts. Try again in {_humanise(retry_after)}.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


def _humanise(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    hours = math.ceil(minutes / 60)
    return f"{hours} hour{'s' if hours > 1 else ''}"


register_limit = rate_limit("auth:register", settings.auth_register_limit)
login_limit = rate_limit("auth:login", settings.auth_login_limit)
refresh_limit = rate_limit("auth:refresh", settings.auth_refresh_limit)
forgot_password_limit = rate_limit("auth:forgot", settings.auth_forgot_password_limit)
verify_email_limit = rate_limit("auth:verify", settings.auth_verify_email_limit)
