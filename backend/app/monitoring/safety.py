"""Deciding whether a URL is safe for the server to fetch.

Users hand us a URL and the worker fetches it from inside our own network.
Without a check that is server-side request forgery: someone tracks
`http://169.254.169.254/...` and the monitor reads cloud instance credentials,
or `http://10.0.0.5/` and reads whatever else is on the private network. The
result comes back through detection and is rendered to them as a "product".

Three things make this harder than a blocklist of hostnames:

1. **Encodings.** `http://2130706433/`, `http://0x7f.1/`, `http://[::1]/` and
   `http://localhost/` are all loopback. Checking the *resolved address* rather
   than the text catches every spelling at once, so that is what happens here.
2. **Redirects.** A perfectly innocent public URL can answer 302 to
   169.254.169.254, so every hop has to be checked, not just the input. The
   fetcher follows redirects by hand for that reason.
3. **DNS rebinding.** A name can resolve to a public address when checked and a
   private one when connected to. The window is small and this does not close
   it — closing it means pinning the connection to the validated address, which
   fights SNI and CDNs. It is the known residual risk here.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Signature of `socket.getaddrinfo`, narrowed to what is used here. Injectable
#: so the rules can be tested without depending on what DNS says today.
Resolver = Callable[[str, int | None], list]


class UnsafeUrlError(ValueError):
    """The URL points somewhere the server must not fetch from."""


def _is_public(address: str) -> bool:
    """Whether an address belongs to the public internet.

    Everything else is refused: loopback, private ranges, link-local (which is
    where cloud metadata lives), multicast, reserved, and unspecified. An
    IPv4-mapped IPv6 address is unwrapped first, since `::ffff:127.0.0.1` is
    loopback wearing a hat.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolved_addresses(hostname: str, port: int | None, resolver: Resolver | None = None) -> list[str]:
    resolve = resolver or (lambda host, prt: socket.getaddrinfo(host, prt, proto=socket.IPPROTO_TCP))
    try:
        return [str(info[4][0]) for info in resolve(hostname, port)]
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve {hostname}.") from exc


def assert_safe_url(url: str, resolver: Resolver | None = None) -> None:
    """Raise UnsafeUrlError unless every address behind this URL is public.

    Every address, not the first: a name that returns one public and one
    private address would otherwise be a way through, since which one is used
    is not ours to decide.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Only http and https are fetched, not {parsed.scheme or 'a relative URL'}.")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("The URL has no host.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("The URL has an invalid port.") from exc

    addresses = resolved_addresses(hostname, port, resolver)
    if not addresses:
        raise UnsafeUrlError(f"Could not resolve {hostname}.")

    for address in addresses:
        if not _is_public(address):
            # The address is deliberately not repeated back to the caller: on a
            # public API, "10.0.0.5 is not public" is a free internal port scan.
            logger.warning("Refused fetch of %s: resolves to non-public %s", hostname, address)
            raise UnsafeUrlError(f"{hostname} does not resolve to a public address.")
