from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before anything imports app.config, which reads the environment
# at import time.
_TMP_DB = Path(tempfile.gettempdir()) / "stockwatch_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_TMP_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("EMAIL_ENABLED", "false")
os.environ.setdefault("RESPECT_ROBOTS_TXT", "false")
os.environ.setdefault("PER_HOST_DELAY_SECONDS", "0")
# Tracking a product asks for an immediate check. The suite must not make
# network requests, so it is off here and asserted directly in test_dispatch.
os.environ.setdefault("CHECK_ON_TRACK", "false")
# Every test that needs a session registers one, and TestClient presents the
# same address each time, so the suite would exhaust the real limit within a
# handful of tests. test_rate_limit.py turns it back on for itself, with the
# small limits set here.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("AUTH_REGISTER_LIMIT", "3/hour")
os.environ.setdefault("AUTH_LOGIN_LIMIT", "3/minute")
os.environ.setdefault("AUTH_REFRESH_LIMIT", "3/minute")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "extension" / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def _clean_database() -> Iterator[None]:
    """A fresh schema per test.

    Slower than wrapping each test in a rolled-back transaction, but immune to
    the commits the API routes legitimately perform.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": "shopper@example.com", "password": "correct-horse-9", "display_name": "Shopper"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def load_fixture(name: str) -> str:
    """Reuse the extension's page fixtures.

    Sharing them is the point: it is the only way to know that a snapshot taken
    in the browser and one taken by a worker agree.
    """
    return (FIXTURES / name).read_text(encoding="utf-8")
