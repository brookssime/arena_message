"""
tests/conftest.py
=================

`conftest.py` is pytest's special file for shared fixtures and setup. pytest imports it
automatically before any test module — which is exactly what we need, because `app.py` reads
its configuration at *import time*. So we must populate the environment variables here, BEFORE
any test does `import app`.

Idiomatic Python / pytest notes for a TS/Kotlin dev:
- A "fixture" is pytest's dependency-injection mechanism. A test function that declares a
  parameter named after a fixture receives whatever that fixture returns. Think of it like a
  per-test `beforeEach` that can also hand you a value.
- `yield` inside a fixture splits it into setup (before `yield`) and teardown (after). That's
  the pytest equivalent of beforeEach/afterEach in one function.
- `monkeypatch` is a built-in fixture for temporarily replacing attributes/env vars; it undoes
  every change automatically when the test finishes.
"""

import os
import tempfile

import pytest

# A throwaway directory for re-hosted media during the whole test run. We create it and point
# MEDIA_DIR at it BEFORE importing app, so app.config.media_dir resolves here (an absolute path)
# instead of the real ./media folder. We deliberately set this one with plain assignment (not
# setdefault) so tests never touch your real media directory.
_TEST_MEDIA_DIR = tempfile.mkdtemp(prefix="arena_message_test_media_")
os.environ["MEDIA_DIR"] = _TEST_MEDIA_DIR

# Other fake-but-valid config so `import app` succeeds. setdefault means "only set if not
# already set", so a real value already in your shell won't be clobbered. The webhook secret
# here is what the tests send in the X-Telegram-Bot-Api-Secret-Token header.
_TEST_ENV = {
    "ARENA_ACCESS_TOKEN": "test-arena-token",
    "ARENA_CHANNEL_SLUG": "staging-y7mhkxq-1mw",
    "TELEGRAM_BOT_TOKEN": "123456:test-bot-token",
    "TELEGRAM_WEBHOOK_SECRET": "test-secret-123",
    "ALLOWED_TELEGRAM_USER_ID": "42",
    "PUBLIC_BASE_URL": "https://example.test/",  # trailing slash on purpose (config strips it)
    "PORT": "8080",
}
for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)


# Constants the tests import, kept in sync with the env above.
WEBHOOK_SECRET = _TEST_ENV["TELEGRAM_WEBHOOK_SECRET"]
ALLOWED_USER_ID = int(_TEST_ENV["ALLOWED_TELEGRAM_USER_ID"])


class FakeArena:
    """A stand-in for ArenaClient that records calls instead of hitting the network."""

    def __init__(self):
        self.calls = []  # a list of tuples describing what was called, for assertions

    def create_block(self, *, source=None, content=None):
        self.calls.append(("create", source, content))
        return {"id": 555, "class": "FakeBlock"}

    def update_block(self, block_id, *, title=None, description=None):
        self.calls.append(("update", block_id, title, description))
        return {"id": block_id}


class FakeTelegram:
    """A stand-in for TelegramClient. download_file returns fixed fake JPEG bytes."""

    def __init__(self):
        self.replies = []

    def download_file(self, file_id):
        return (b"\xff\xd8\xff fake-jpeg-bytes", "image/jpeg")

    def send_message(self, chat_id, text):
        self.replies.append((chat_id, text))


@pytest.fixture
def fakes(monkeypatch):
    """
    Swap the real are.na/Telegram clients for test doubles, and start each test with an empty
    media directory so file-count assertions are reliable.

    Returns a small namespace exposing `.arena`, `.telegram`, and `.media_dir` so tests can
    inspect what got called and what got written.

    Note we DON'T monkeypatch config.media_dir: Config is a frozen dataclass (immutable), and
    we already pointed MEDIA_DIR at a temp dir above. Patching only the two client objects
    (plain module attributes) keeps teardown simple and safe.
    """
    import app

    # Start clean: remove any files a previous test left in the shared temp media dir.
    for existing in app.config.media_dir.iterdir():
        existing.unlink()

    fake_arena = FakeArena()
    fake_telegram = FakeTelegram()
    # monkeypatch.setattr temporarily replaces module-level objects; undone after the test.
    monkeypatch.setattr(app, "arena", fake_arena)
    monkeypatch.setattr(app, "telegram", fake_telegram)

    # types.SimpleNamespace is a quick anonymous object (like a JS object literal), handy for
    # bundling a few related values without defining a class.
    import types
    return types.SimpleNamespace(
        arena=fake_arena, telegram=fake_telegram, media_dir=app.config.media_dir
    )


@pytest.fixture
def client():
    """A Flask test client — lets us make requests without starting a real server/network."""
    import app
    return app.app.test_client()
