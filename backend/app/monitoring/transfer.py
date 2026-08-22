"""One HTTP exchange, with the limits that make it safe to point at a stranger.

Split out of `fetcher` because the retry-and-backoff policy and the
what-is-safe-to-connect-to rules are different concerns, and only the second
one is worth reading closely.

Two departures from just calling `client.get(url, follow_redirects=True)`:

* **Redirects are followed by hand.** A public URL that answers 302 to
  169.254.169.254 defeats a check performed only on the input, so every hop is
  validated before it is taken.
* **The body is streamed against a ceiling.** `response.text` reads whatever
  arrives; one URL serving an endless body is enough to take a worker down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.monitoring.safety import UnsafeUrlError, assert_safe_url

logger = logging.getLogger(__name__)

REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


class ResponseTooLarge(Exception):
    """The body passed the ceiling and the read was abandoned."""


class TooManyRedirects(Exception):
    pass


@dataclass(slots=True)
class Fetched:
    status_code: int
    text: str
    url: str


def _guarded(url: str) -> None:
    if settings.fetch_guard_enabled:
        assert_safe_url(url)


def _read_capped(response: httpx.Response, limit: int) -> str:
    """Read the body, giving up the moment it exceeds the ceiling.

    Counted in bytes as they arrive rather than checking Content-Length, which
    a hostile server is free to understate or omit.
    """
    chunks: list[bytes] = []
    total = 0

    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge(f"Response exceeded {limit} bytes.")
        chunks.append(chunk)

    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    # Stores serve broken bytes more often than anyone would like, and a
    # mis-declared charset should not lose an otherwise fine page.
    return body.decode(encoding, errors="replace")


def get(client: httpx.Client, url: str, headers: dict[str, str]) -> Fetched:
    """Fetch one URL, following redirects safely.

    Raises UnsafeUrlError if the URL — or anywhere it redirects to — is not a
    public address.
    """
    current = url

    for _ in range(settings.max_redirects + 1):
        _guarded(current)

        with client.stream("GET", current, headers=headers, follow_redirects=False) as response:
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    raise httpx.HTTPError(f"HTTP {response.status_code} without a Location header.")
                # Relative redirects are ordinary and must resolve against the
                # URL we actually fetched, not the one we started from.
                current = urljoin(current, location)
                continue

            return Fetched(
                status_code=response.status_code,
                text=_read_capped(response, settings.max_response_bytes),
                url=str(response.url),
            )

    raise TooManyRedirects(f"More than {settings.max_redirects} redirects.")


__all__ = [
    "Fetched",
    "ResponseTooLarge",
    "TooManyRedirects",
    "UnsafeUrlError",
    "get",
]
