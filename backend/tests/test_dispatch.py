"""A freshly tracked product gets checked without anybody asking."""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks

from app.config import settings
from app.services import dispatch


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "check_on_track", True)


def test_nothing_is_arranged_when_the_feature_is_off():
    """The suite's own precondition: no test makes a network request."""
    assert dispatch.request_check(1, BackgroundTasks()) == "disabled"


def test_it_falls_back_to_the_api_process_when_there_is_no_queue(enabled, monkeypatch):
    """A free deployment has no Redis, and must still check the product."""

    def no_broker(*_args, **_kwargs):
        raise OSError("broker unreachable")

    monkeypatch.setattr("app.worker.check_one.apply_async", no_broker)
    background = BackgroundTasks()

    assert dispatch.request_check(7, background) == "background"
    assert len(background.tasks) == 1


def test_it_uses_the_queue_when_there_is_one(enabled, monkeypatch):
    sent: list[object] = []
    monkeypatch.setattr(
        "app.worker.check_one.apply_async",
        lambda *args, **kwargs: sent.append(kwargs.get("args")),
    )
    background = BackgroundTasks()

    assert dispatch.request_check(7, background) == "queued"
    assert sent == [[7]]
    # The queue owns it now; running it here as well would check twice.
    assert background.tasks == []


def test_a_broken_queue_never_fails_the_request(enabled, monkeypatch):
    """Tracking succeeded. Losing it because the queue is down would be worse."""

    def no_broker(*_args, **_kwargs):
        raise OSError("broker unreachable")

    monkeypatch.setattr("app.worker.check_one.apply_async", no_broker)

    assert dispatch.request_check(7, None) == "deferred"


def test_tracking_asks_for_a_check(client, auth_headers, enabled, monkeypatch):
    """End to end: the route arranges it, whatever the deployment."""
    asked: list[int] = []
    monkeypatch.setattr(
        "app.api.routes.products.request_check",
        lambda product_id, background: asked.append(product_id) or "queued",
    )

    from tests.test_api import TRACK_PAYLOAD

    response = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers)

    assert response.status_code in (200, 201)
    assert asked == [response.json()["id"]]
