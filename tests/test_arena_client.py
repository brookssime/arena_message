"""
tests/test_arena_client.py
=========================

Tests for ArenaClient's request-building and validation logic, WITHOUT real network calls.
We replace the client's internal `_session` with a fake that records requests and returns a
canned response.
"""

import pytest

from arena_client import ArenaClient


class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, json_body):
        self._json_body = json_body

    def raise_for_status(self):
        # Pretend every response is a success (2xx). Real code would raise on 4xx/5xx.
        return None

    def json(self):
        return self._json_body


class FakeSession:
    """Records the last POST/PUT so tests can assert on URL + payload."""

    def __init__(self):
        self.headers = {}
        self.last_post = None
        self.last_put = None

    def post(self, url, json=None, timeout=None):
        self.last_post = {"url": url, "json": json, "timeout": timeout}
        return FakeResponse({"id": 1, "class": "Image"})

    def put(self, url, json=None, timeout=None):
        self.last_put = {"url": url, "json": json, "timeout": timeout}
        return FakeResponse({"id": 1})


@pytest.fixture
def arena_with_fake_session():
    """An ArenaClient whose network layer is a FakeSession we can inspect."""
    client = ArenaClient("token-abc", "staging-y7mhkxq-1mw")
    fake = FakeSession()
    client._session = fake  # reach in and replace the real session
    return client, fake


def test_create_block_with_source_builds_correct_request(arena_with_fake_session):
    client, fake = arena_with_fake_session
    client.create_block(source="https://example.test/media/x.jpg")

    assert fake.last_post["url"].endswith("/blocks")
    # Only `source` should be in the body (not `content`).
    assert fake.last_post["json"] == {
        "value": "https://example.test/media/x.jpg",
        "channel_ids": [client.channel_slug],
    }
    # We always set a timeout on network calls.
    assert fake.last_post["timeout"] is not None


def test_create_block_with_content_builds_correct_request(arena_with_fake_session):
    client, fake = arena_with_fake_session
    client.create_block(content="a note")
    assert fake.last_post["json"] == {
        "value": "a note",
        "channel_ids": [client.channel_slug],
    }


def test_create_block_rejects_both_source_and_content(arena_with_fake_session):
    client, _ = arena_with_fake_session
    # are.na forbids sending both; we guard against it before the request goes out.
    with pytest.raises(ValueError):
        client.create_block(source="https://x", content="y")


def test_create_block_rejects_neither(arena_with_fake_session):
    client, _ = arena_with_fake_session
    with pytest.raises(ValueError):
        client.create_block()


def test_update_block_omits_none_fields(arena_with_fake_session):
    client, fake = arena_with_fake_session
    client.update_block(99, description="just a caption")  # title left as None

    assert fake.last_put["url"].endswith("/blocks/99")
    # `title` must NOT appear, since we didn't pass it.
    assert fake.last_put["json"] == {"description": "just a caption"}


def test_update_block_requires_at_least_one_field(arena_with_fake_session):
    client, _ = arena_with_fake_session
    with pytest.raises(ValueError):
        client.update_block(99)
