"""The auth endpoints refuse to be hammered.

Limits are set small in conftest so these tests cost four requests rather than
a hundred; the shipped defaults live in app/config.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.api.limiter import limiter
from app.config import settings


@pytest.fixture
def limited() -> Iterator[None]:
    """Turn the limiter on for one test, and leave no counters behind."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.reset()
    limiter.enabled = settings.rate_limit_enabled


def _register(client, n: int):
    return client.post(
        "/api/auth/register",
        json={"email": f"shopper{n}@example.com", "password": "correct-horse-9"},
    )


def test_registration_stops_after_the_limit(client, limited):
    assert [_register(client, n).status_code for n in range(3)] == [201, 201, 201]

    blocked = _register(client, 3)
    assert blocked.status_code == 429
    # The extension renders `detail`; anything else surfaces as "Request failed".
    assert "Too many attempts" in blocked.json()["detail"]
    assert blocked.headers["Retry-After"]


def test_wrong_passwords_stop_after_the_limit(client, limited):
    assert _register(client, 0).status_code == 201

    attempts = [
        client.post("/api/auth/login", json={"email": "shopper0@example.com", "password": "wrong"})
        for _ in range(3)
    ]
    assert [attempt.status_code for attempt in attempts] == [401, 401, 401]

    # Including the right one: an attacker who guesses on the last attempt must
    # not be let through, so the limit is on the endpoint, not on failures.
    blocked = client.post(
        "/api/auth/login",
        json={"email": "shopper0@example.com", "password": "correct-horse-9"},
    )
    assert blocked.status_code == 429


def test_limits_are_off_unless_configured(client):
    """The suite's own precondition: without the fixture, nothing is limited."""
    assert [_register(client, n).status_code for n in range(5)] == [201] * 5
