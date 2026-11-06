"""Tests for the RCA_DATABASE_URL setting (durable PostgreSQL datastore).

The field is optional at the Settings level (defaults to None); the
mandatory-DB fail-fast is enforced later in the store layer, not here.
"""
from __future__ import annotations

from rca_agent.config import Settings


def test_database_url_read_from_env(monkeypatch):
    url = "postgresql://rca:secret@db-pg:5432/rca"
    monkeypatch.setenv("RCA_DATABASE_URL", url)
    # Construct a fresh Settings (not the cached get_settings singleton) so the
    # env var is picked up for this test in isolation.
    settings = Settings()
    assert settings.database_url == url


def test_database_url_defaults_to_none(monkeypatch):
    monkeypatch.delenv("RCA_DATABASE_URL", raising=False)
    settings = Settings()
    assert settings.database_url is None
