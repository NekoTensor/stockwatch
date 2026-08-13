"""Settings that only break outside the test suite.

The bug this file exists for could not be caught by any other test here: it
needed a real environment variable, which is exactly what docker compose
supplies and what a local `uvicorn` run - reading defaults, because there is no
`backend/.env` - does not. The API crashlooped before binding a port, and the
only symptom the user saw was the extension reporting it could not reach the
backend.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def test_cors_origins_reads_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch):
    """The format `.env.example` documents has to be the format that parses.

    pydantic-settings decodes complex annotations (list, dict, set) as JSON
    before validators run, so `list[str]` alone would reject this string as
    malformed JSON rather than passing it to the splitter.
    """
    monkeypatch.setenv("CORS_ORIGINS", "chrome-extension://*,http://localhost:5173")

    assert Settings().cors_origins == ["chrome-extension://*", "http://localhost:5173"]


def test_cors_origins_tolerates_spacing_and_trailing_commas(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://a.example , https://b.example ,")

    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_cors_origins_falls_back_to_the_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert "chrome-extension://*" in Settings().cors_origins
