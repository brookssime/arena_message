"""
config.py
=========

Centralizes all configuration for the app. Everything the program needs to know that
might change between your laptop and the cloud (secrets, the channel slug, the public URL)
is read from *environment variables* here, in one place.

Why a dedicated config module?
- In TypeScript you might reach for `process.env.FOO` scattered across files, or a config
  object exported from one module. This is the Python equivalent of that single config module:
  read + validate the environment once, fail loudly if something required is missing, and let
  the rest of the code import clean, already-validated values.

Idiomatic Python notes for a TS/Kotlin dev:
- There's no `const`/`val` keyword. By *convention*, module-level names in ALL_CAPS are treated
  as constants. Python won't stop you reassigning them, but nobody does.
- `os.environ` is a dict-like object of the process environment (like `process.env`).
- We use a small `dataclass` to bundle config into one immutable object. A `@dataclass` is
  roughly Kotlin's `data class` / a TS interface-with-a-constructor: it auto-generates
  `__init__`, `__repr__`, equality, etc. `frozen=True` makes instances read-only.
"""

from __future__ import annotations  # lets us write modern type hints on older runtimes

import os
from dataclasses import dataclass
from pathlib import Path

# `python-dotenv` reads a local `.env` file and loads it into os.environ.
# In production (Render) there is no `.env` file — the platform injects real env vars —
# so load_dotenv() simply finds nothing and does nothing. That's exactly what we want.
from dotenv import load_dotenv

load_dotenv()  # call once, at import time, before we read any variables below


# A tiny helper. Python has no built-in "required env var or throw" function, so we write one.
# Note the type hint `-> str`: this function always returns a string or raises; it never
# returns None. That's a contract the caller (and your editor) can rely on.
def _required(name: str) -> str:
    """Read an env var that MUST be present, or raise a clear error explaining what's missing."""
    value = os.environ.get(name)
    # In Python, an empty string is "falsy" (like JS), so `not value` catches both unset
    # (None) and accidentally-empty ("") values in one check.
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file (local) or as a platform secret (production)."
        )
    return value


def _optional(name: str, default: str) -> str:
    """Read an env var that has a sensible default if unset."""
    # dict.get(key, default) returns `default` when the key is absent — no KeyError, unlike [].
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Config:
    """
    An immutable bundle of every setting the app needs.

    Grouping config into one object (instead of importing loose globals everywhere) makes it
    obvious what the app depends on, and makes it trivial to construct a fake Config in tests.
    """

    # --- are.na ---
    arena_access_token: str   # Personal Access Token, WRITE scope. SECRET.
    arena_channel_slug: str   # e.g. "staging-y7mhkxq-1mw"

    # --- Telegram ---
    telegram_bot_token: str       # from @BotFather. SECRET.
    telegram_webhook_secret: str  # random string Telegram echoes back to prove it's really Telegram. SECRET.
    allowed_telegram_user_id: int # only messages from THIS user id are accepted

    # --- This server ---
    public_base_url: str  # e.g. "https://your-app.onrender.com" — used to build media URLs + webhook URL
    media_dir: Path       # where downloaded photos are stored before are.na fetches them
    port: int             # local dev port (the cloud host usually sets $PORT for us)


def load_config() -> Config:
    """
    Build a validated Config from the environment.

    We call this once at startup. If anything required is missing, this raises immediately —
    "fail fast" — so you find the problem on boot instead of halfway through handling a message.
    """
    # `.rstrip("/")` defends against a trailing slash in the URL (so we don't build
    # "https://host//media/..."). Small papercut, easy to prevent here.
    public_base_url = _required("PUBLIC_BASE_URL").rstrip("/")

    # Path is the idiomatic way to handle filesystem paths (vs. raw string concatenation).
    # `.expanduser()` turns a leading "~" into your home directory.
    media_dir = Path(_optional("MEDIA_DIR", "./media")).expanduser()

    return Config(
        arena_access_token=_required("ARENA_ACCESS_TOKEN"),
        arena_channel_slug=_required("ARENA_CHANNEL_SLUG"),
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        telegram_webhook_secret=_required("TELEGRAM_WEBHOOK_SECRET"),
        # Env vars are always strings, so we convert to int explicitly. int("abc") would raise
        # a ValueError with a clear message, which is fine — better than silently misbehaving.
        allowed_telegram_user_id=int(_required("ALLOWED_TELEGRAM_USER_ID")),
        public_base_url=public_base_url,
        media_dir=media_dir,
        port=int(_optional("PORT", "8080")),
    )
