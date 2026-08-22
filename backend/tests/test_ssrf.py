"""The server refuses to fetch its own network on a stranger's instruction.

Resolution is stubbed throughout: these assert the *rules*, and a test that
depended on what DNS says today would be a test that fails on an aeroplane.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from app.config import settings
from app.monitoring import transfer
from app.monitoring.safety import UnsafeUrlError, assert_safe_url

PUBLIC = "93.184.216.34"


def resolver_for(*addresses: str):
    """A getaddrinfo stand-in returning exactly these addresses."""

    def resolve(host, port, **_kwargs):  # noqa: ANN001, ANN202, ARG001
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 80)) for address in addresses]

    return resolve


def failing_resolver(host, port, **_kwargs):  # noqa: ANN001, ANN202, ARG001
    raise socket.gaierror("no such host")


@pytest.fixture(autouse=True)
def _guard_on(monkeypatch):
    """The suite runs with the guard off; these tests are about the guard."""
    monkeypatch.setattr(settings, "fetch_guard_enabled", True)


# ------------------------------------------------------------ the rules ----


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",          # loopback
        "10.0.0.5",           # private
        "172.16.0.1",         # private
        "192.168.1.1",        # private
        "169.254.169.254",    # link-local: cloud instance metadata
        "0.0.0.0",            # unspecified
        "::1",                # loopback, v6
        "fd00::1",            # unique local, v6
        "fe80::1",            # link-local, v6
        "::ffff:127.0.0.1",   # loopback wearing an IPv6 hat
        "224.0.0.1",          # multicast
    ],
)
def test_non_public_addresses_are_refused(address):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://shop.example/p/1", resolver=resolver_for(address))


def test_a_public_address_is_allowed():
    # The assertion is that it returns rather than raising.
    assert_safe_url("https://shop.example/p/1", resolver=resolver_for(PUBLIC))


def test_every_address_must_be_public():
    """One public answer alongside a private one is not a pass.

    Which address gets connected to is not ours to decide, so a name that
    returns both is a way through unless all of them are checked.
    """
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://shop.example/p/1", resolver=resolver_for(PUBLIC, "10.0.0.5"))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/x",
        "/relative/path",
    ],
)
def test_only_http_and_https_are_fetched(url):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url, resolver=resolver_for(PUBLIC))


def test_an_unresolvable_host_is_refused():
    """Refusing beats guessing: an unknown address cannot be shown to be public."""
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://nowhere.invalid/p", resolver=failing_resolver)


def test_the_error_does_not_leak_the_address():
    """Otherwise the API is a free internal port scanner."""
    with pytest.raises(UnsafeUrlError) as caught:
        assert_safe_url("https://shop.example/p/1", resolver=resolver_for("10.1.2.3"))

    assert "10.1.2.3" not in str(caught.value)


def test_alternative_spellings_of_loopback_are_caught():
    """Decimal and hex encodings resolve like anything else, which is the point
    of checking the resolved address rather than the text."""
    for spelling in ("http://2130706433/", "http://0x7f000001/", "http://[::1]/"):
        with pytest.raises(UnsafeUrlError):
            assert_safe_url(spelling, resolver=resolver_for("127.0.0.1"))


# -------------------------------------------------------------- redirects ----


def test_a_redirect_into_the_private_network_is_refused(monkeypatch):
    """The input is public; the destination is not. Checking only the input
    would follow it straight to the metadata service."""

    def resolve(host, port, **_kwargs):  # noqa: ANN001, ANN202, ARG001
        address = "169.254.169.254" if host == "metadata.example" else PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 80))]

    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "shop.example":
            return httpx.Response(302, headers={"location": "http://metadata.example/latest/meta-data/"})
        return httpx.Response(200, text="should never be reached")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(UnsafeUrlError):
        transfer.get(client, "https://shop.example/p/1", {})


def test_an_ordinary_redirect_is_followed(monkeypatch):
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for(PUBLIC))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/p/1":
            return httpx.Response(301, headers={"location": "/p/final"})
        return httpx.Response(200, text="x" * 500)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = transfer.get(client, "https://shop.example/p/1", {})

    assert result.status_code == 200
    assert result.url.endswith("/p/final")


def test_a_redirect_loop_gives_up(monkeypatch):
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for(PUBLIC))

    handler = lambda request: httpx.Response(302, headers={"location": "/loop"})  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(transfer.TooManyRedirects):
        transfer.get(client, "https://shop.example/loop", {})


# ------------------------------------------------------------------ size ----


def test_an_oversized_body_is_abandoned(monkeypatch):
    """One URL serving an endless body must not take the worker down."""
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for(PUBLIC))
    monkeypatch.setattr(settings, "max_response_bytes", 1000)

    handler = lambda request: httpx.Response(200, content=b"x" * 5000)  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(transfer.ResponseTooLarge):
        transfer.get(client, "https://shop.example/big", {})


def test_a_body_under_the_ceiling_is_read(monkeypatch):
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for(PUBLIC))
    monkeypatch.setattr(settings, "max_response_bytes", 10_000)

    handler = lambda request: httpx.Response(200, content=b"y" * 5000)  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert len(transfer.get(client, "https://shop.example/ok", {}).text) == 5000


# ------------------------------------------------------------------- api ----


def test_tracking_a_private_address_is_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for("169.254.169.254"))

    response = client.post(
        "/api/products/track",
        json={
            "url": "http://metadata.example/latest/meta-data/",
            "name": "not a product",
            "availability": "in_stock",
            "variants": [],
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "169.254" not in response.text


def test_detecting_a_private_address_is_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.monitoring.safety.socket.getaddrinfo", resolver_for("127.0.0.1"))

    response = client.post(
        "/api/products/detect",
        json={"url": "http://localhost.example/admin"},
        headers=auth_headers,
    )

    assert response.status_code == 400
