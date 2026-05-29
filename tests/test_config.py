"""
tests/test_config.py
====================

Tests for configuration loading: required-var enforcement, the trailing-slash fix on the
public URL, and string->int conversion.

pytest discovers any function named `test_*` in any `test_*.py` file — no registration needed
(this is "convention over configuration", similar to JUnit's @Test by naming).
"""

import pytest

from config import load_config


def test_load_config_reads_values():
    """With the test env from conftest, config should load and normalize values."""
    config = load_config()
    # The trailing slash on PUBLIC_BASE_URL must be stripped so we don't build "...//media".
    assert config.public_base_url == "https://example.test"
    # ALLOWED_TELEGRAM_USER_ID arrives as a string env var and must become an int.
    assert config.allowed_telegram_user_id == 42
    assert isinstance(config.allowed_telegram_user_id, int)


def test_missing_required_var_raises(monkeypatch):
    """A missing required secret should fail fast with a clear RuntimeError."""
    # Remove a required var for the duration of this test only.
    monkeypatch.delenv("ARENA_ACCESS_TOKEN", raising=False)

    # pytest.raises asserts that the block raises the given exception type. `match` checks the
    # message via regex — here we confirm the error names the missing variable.
    with pytest.raises(RuntimeError, match="ARENA_ACCESS_TOKEN"):
        load_config()


def test_empty_required_var_also_raises(monkeypatch):
    """An empty string counts as missing (empty strings are falsy in Python)."""
    monkeypatch.setenv("ARENA_CHANNEL_SLUG", "")
    with pytest.raises(RuntimeError, match="ARENA_CHANNEL_SLUG"):
        load_config()
