"""Configuration that decides whether alerts can leave the building."""

from __future__ import annotations

import pytest

from app.config import Settings

PRODUCTION = {
    "environment": "production",
    "database_url": "postgresql+psycopg://u:p@db:5432/stockwatch",
}


@pytest.fixture(autouse=True)
def _clean_email_env(monkeypatch):
    """conftest pins EMAIL_ENABLED for the suite; these tests are about the default."""
    monkeypatch.delenv("EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)


def test_a_provider_key_turns_email_on():
    assert Settings(resend_api_key="re_test_key").email_enabled is True


def test_no_provider_key_leaves_email_off():
    assert Settings().email_enabled is False


def test_an_explicit_setting_still_wins(monkeypatch):
    """Keeping the key while sending is paused has to remain possible."""
    monkeypatch.setenv("EMAIL_ENABLED", "false")
    assert Settings(resend_api_key="re_test_key").email_enabled is False


def test_production_rejects_an_undeliverable_sender():
    settings = Settings(**PRODUCTION, resend_api_key="re_test_key")

    problems = settings.check_production()

    # The shipped default, .local, is not a domain any provider will send from.
    assert any("EMAIL_FROM" in problem for problem in problems)


def test_production_accepts_a_verified_sender():
    settings = Settings(
        **PRODUCTION,
        resend_api_key="re_test_key",
        email_from="StockWatch <alerts@stockwatch.app>",
    )

    assert settings.check_production() == []


def test_production_warns_when_email_is_off_without_refusing_to_start():
    settings = Settings(**PRODUCTION)

    assert settings.check_production() == []
    assert any("Email is off" in warning for warning in settings.production_warnings())


def test_development_is_warned_about_nothing():
    assert Settings().production_warnings() == []
