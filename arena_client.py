"""
arena_client.py
===============

A tiny client for the parts of the are.na API we use: creating a block in a channel, and
updating a block's title/description afterward.

We deliberately use the `requests` library directly instead of a third-party "arena" wrapper.
Reasons: the API surface we need is two endpoints, `requests` is the de-facto standard HTTP
library, and writing it ourselves keeps every moving part visible (good for learning).

Idiomatic Python notes for a TS/Kotlin dev:
- This is a *class* that holds configuration (the token + slug + a reused HTTP session).
  In TS you might write a class with a constructor storing `this.token`; here `__init__` is the
  constructor and `self` is the explicit `this` (Python passes the instance in explicitly).
- `requests.Session` is like keeping a configured fetch client around: it reuses the underlying
  TCP connection and lets us set the auth header once for every request.
- Keyword-only arguments: the `*` in `create_block(self, *, source=..., content=...)` forces
  callers to write `create_block(source=...)` rather than positional `create_block(x)`. That
  makes call sites self-documenting and prevents mixing up the two mutually-exclusive params.
- We raise exceptions on failure rather than returning error codes. Idiomatic Python is
  "ask forgiveness, not permission" — let it throw, and let the caller decide how to handle it.
"""

from __future__ import annotations

import requests

# The base URL for are.na's (v3) REST API.
ARENA_API_BASE = "https://api.are.na/v3"

# How long we'll wait on are.na before giving up, in seconds. ALWAYS set a timeout on network
# calls — without one, `requests` can hang forever and freeze the whole web worker.
_TIMEOUT_SECONDS = 30


class ArenaClient:
    """Minimal are.na API client scoped to a single channel."""

    def __init__(self, access_token: str, channel_slug: str) -> None:
        # `self.<name> = ...` declares + assigns instance fields. There's no separate field
        # declaration block like in Kotlin/TS — attributes spring into existence on assignment.
        self.channel_slug = channel_slug

        # A Session lets us attach the Authorization header once and reuse it for every call.
        self._session = requests.Session()
        self._session.headers.update(
            {
                # are.na uses standard OAuth2 bearer auth. The Personal Access Token goes here.
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )

    def create_block(
        self, *, source: str | None = None, content: str | None = None
    ) -> dict:
        """
        Create a block in the channel.

        Pass EITHER `source` (a URL — are.na auto-detects image / link / embed) OR `content`
        (markdown text). The are.na API rejects both at once, so we guard against that here
        with a clear error rather than letting the API return a confusing 422.

        Returns the created block as a dict (parsed JSON). The important field is `block["id"]`,
        which we need if we later want to attach a caption via `update_block`.
        """
        # `bool(source)` is True for a non-empty string, False for None/"". XOR-style check:
        # exactly one of the two must be provided.
        if bool(source) == bool(content):
            raise ValueError(
                "create_block requires exactly one of `source` or `content`."
            )

        # Build the request body. A dict here becomes a JSON object on the wire (json=...).
        payload = {"value": source or content, "channel_ids": [self.channel_slug]}

        url = f"{ARENA_API_BASE}/blocks"
        response = self._session.post(url, json=payload, timeout=_TIMEOUT_SECONDS)

        # raise_for_status() turns any 4xx/5xx into an exception. Without it, a failed request
        # would silently look "successful" and we'd try to parse an error body as a block.
        response.raise_for_status()
        return response.json()

    def update_block(
        self,
        block_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict:
        """
        Update a block's title and/or description (e.g. to store a photo's caption).

        Only the fields you pass are sent; anything left as None is omitted from the request
        so we don't accidentally blank out existing values.
        """
        # Dict comprehension: build a dict containing only the keys whose value isn't None.
        # This is the Pythonic way to assemble "just the fields that were provided" — compare
        # to spreading a filtered object in TS. `.items()` yields (key, value) pairs.
        payload = {
            key: value
            for key, value in {"title": title, "description": description}.items()
            if value is not None
        }
        if not payload:
            raise ValueError(
                "update_block needs at least one of `title` or `description`."
            )

        url = f"{ARENA_API_BASE}/blocks/{block_id}"
        response = self._session.put(url, json=payload, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
