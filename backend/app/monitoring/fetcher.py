"""Fetching product pages, politely.

Design constraints, in priority order:

0. **Never fetch somewhere the user should not be able to reach.** The URL is
   theirs, the network is ours; see `safety` and `transfer`.
1. **Never look like an attack.** One request at a time per host, a minimum gap
   between them, and honest identification in the User-Agent.
2. **Never mistake our own failure for a fact about the product.** Every failure
   mode maps to a `CheckStatus`, and the caller turns anything other than `OK`
   into "keep the previous state".
3. **Back off when asked.** 429 and 403 mean stop, not retry harder.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models.enums import CheckStatus
from app.monitoring import transfer
from app.monitoring.safety import UnsafeUrlError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FetchResult:
    status: CheckStatus
    html: str | None = None
    http_status: int | None = None
    attempts: int = 0
    error: str | None = None
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is CheckStatus.OK and bool(self.html)


class HostThrottle:
    """A minimum gap between requests to the same host, process-wide.

    Deliberately a simple lock-and-sleep rather than a token bucket: the whole
    point is that requests to one store are serialised, and a bucket would allow
    a burst.
    """

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, delay_override: float | None = None) -> None:
        delay = delay_override if delay_override is not None else self._delay
        if delay <= 0:
            return

        with self._lock:
            now = time.monotonic()
            previous = self._last.get(host)
            if previous is not None:
                remaining = delay - (now - previous)
                if remaining > 0:
                    time.sleep(remaining)
                    now = time.monotonic()
            # A little jitter so a batch of products on one store does not
            # produce a perfectly periodic request pattern.
            self._last[host] = now + random.uniform(0, delay * 0.15)


_throttle = HostThrottle(settings.per_host_delay_seconds)
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_robots_lock = threading.Lock()


def _robots_allows(url: str, user_agent: str) -> bool:
    """Check robots.txt, caching one parser per host.

    A host whose robots.txt cannot be fetched is treated as permitted: a
    transient 500 on /robots.txt should not silently stop every check.
    """
    if not settings.respect_robots_txt:
        return True

    host = urlparse(url).netloc
    if not host:
        return True

    with _robots_lock:
        if host not in _robots_cache:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
            try:
                parser.read()
                _robots_cache[host] = parser
            except Exception:  # noqa: BLE001
                logger.debug("Could not read robots.txt for %s; proceeding", host)
                _robots_cache[host] = None
        parser = _robots_cache[host]

    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001
        return True


DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_page(
    url: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    delay_override: float | None = None,
    client: httpx.Client | None = None,
) -> FetchResult:
    """Fetch one product page with retries and exponential backoff."""
    timeout = timeout if timeout is not None else settings.request_timeout_seconds
    retries = max_retries if max_retries is not None else settings.max_retries
    host = urlparse(url).netloc

    if not _robots_allows(url, settings.user_agent):
        logger.info("robots.txt disallows %s", url)
        return FetchResult(status=CheckStatus.BLOCKED, error="Disallowed by robots.txt")

    headers = {**DEFAULT_HEADERS, "User-Agent": settings.user_agent}
    owns_client = client is None
    http = client or httpx.Client(
        # Redirects are followed inside `transfer`, one hop at a time, so that
        # each destination is checked before it is fetched.
        timeout=timeout, follow_redirects=False, headers=headers, http2=False
    )

    attempts = 0
    last_error: str | None = None
    last_status: int | None = None

    try:
        for attempt in range(retries + 1):
            attempts = attempt + 1
            _throttle.wait(host, delay_override)

            try:
                response = transfer.get(http, url, headers)
            except UnsafeUrlError as exc:
                # Not retryable and not the store's fault: the address itself is
                # refused. Returned rather than raised so the caller records it
                # against the product like any other failed check.
                logger.warning("Refused to fetch %s: %s", url, exc)
                return FetchResult(
                    status=CheckStatus.BLOCKED,
                    attempts=attempts,
                    error=str(exc),
                )
            except transfer.ResponseTooLarge as exc:
                logger.warning("Abandoned oversized response from %s: %s", url, exc)
                return FetchResult(status=CheckStatus.FAILED, attempts=attempts, error=str(exc))
            except transfer.TooManyRedirects as exc:
                return FetchResult(status=CheckStatus.FAILED, attempts=attempts, error=str(exc))
            except httpx.TimeoutException as exc:
                last_error = f"Timeout after {timeout}s"
                logger.warning("Timeout fetching %s (attempt %d): %s", url, attempts, exc)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Transport error fetching %s (attempt %d): %s", url, attempts, exc)
            else:
                last_status = response.status_code

                if response.status_code in (404, 410):
                    return FetchResult(
                        status=CheckStatus.NOT_FOUND,
                        http_status=response.status_code,
                        attempts=attempts,
                        error="Product page no longer exists.",
                    )

                if response.status_code in (401, 403, 429):
                    # Being rate limited or blocked is not something to retry
                    # our way out of; stop and let the backoff schedule handle it.
                    return FetchResult(
                        status=CheckStatus.BLOCKED,
                        http_status=response.status_code,
                        attempts=attempts,
                        error=f"Blocked by the store (HTTP {response.status_code}).",
                    )

                if 200 <= response.status_code < 300:
                    text = response.text
                    if not text or len(text) < 200:
                        last_error = "Response body was empty or too short to parse."
                    else:
                        return FetchResult(
                            status=CheckStatus.OK,
                            html=text,
                            http_status=response.status_code,
                            attempts=attempts,
                            final_url=response.url,
                        )
                else:
                    last_error = f"HTTP {response.status_code}"

            if attempt < retries:
                # Exponential backoff with jitter: 1s, 2s, 4s (+/- 25%).
                delay = (2**attempt) * (1 + random.uniform(-0.25, 0.25))
                time.sleep(max(0.5, delay))

        return FetchResult(
            status=CheckStatus.FAILED,
            http_status=last_status,
            attempts=attempts,
            error=last_error or "Unknown fetch failure.",
        )
    finally:
        if owns_client:
            http.close()
