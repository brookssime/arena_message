"""
telegram_client.py
==================

A tiny client for the Telegram Bot API calls we need:
- `download_file(file_id)` — turn a Telegram file id into actual image bytes.
- `send_message(chat_id, text)` — send you a short confirmation reply.

Why download files instead of handing Telegram's URL to are.na?
Telegram's file-download URL looks like:
    https://api.telegram.org/file/bot<YOUR_BOT_TOKEN>/<path>
Notice the bot token is embedded right in the URL. If we passed that to are.na, we'd be
storing our secret bot token inside an are.na block for anyone to read. So instead the SERVER
downloads the bytes (using the token privately), then re-hosts them at a safe public URL.

Idiomatic Python notes for a TS/Kotlin dev:
- `download_file` returns a *tuple* `(bytes, str)`. Tuples are lightweight fixed-size groupings
  (like a Kotlin `Pair`). Callers unpack with `data, content_type = client.download_file(id)`.
- `bytes` is Python's immutable binary-data type (think Kotlin ByteArray / a Node Buffer).
"""

from __future__ import annotations

import requests

_TIMEOUT_SECONDS = 30


class TelegramClient:
    """Minimal Telegram Bot API client."""

    def __init__(self, bot_token: str) -> None:
        # We keep the token private (single leading underscore = "internal by convention";
        # Python has no real `private`, this is a signal to other humans, not the compiler).
        self._bot_token = bot_token
        # Two base URLs: one for API methods, one for downloading file *contents*.
        self._api_base = f"https://api.telegram.org/bot{bot_token}"
        self._file_base = f"https://api.telegram.org/file/bot{bot_token}"
        self._session = requests.Session()

    def _get_file_path(self, file_id: str) -> str:
        """
        Resolve a `file_id` (what arrives in the webhook) into a `file_path` we can download.

        Telegram's design splits this into two steps: first `getFile` to get a short-lived
        path, then a separate GET to fetch the bytes. We hide that two-step dance in here.
        """
        response = self._session.get(
            f"{self._api_base}/getFile",
            params={"file_id": file_id},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # Telegram wraps every response in {"ok": true, "result": {...}}. We dig out the path.
        body = response.json()
        return body["result"]["file_path"]

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        """
        Download a Telegram file's raw bytes.

        Returns a tuple of (raw_bytes, content_type). The content type (e.g. "image/jpeg")
        lets the caller pick the right file extension when re-hosting.

        Note: Telegram's cloud API caps downloads at 20 MB, which is plenty for phone photos.
        """
        file_path = self._get_file_path(file_id)
        response = self._session.get(f"{self._file_base}/{file_path}", timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()

        # `.content` is the raw response body as bytes (vs `.text`, which decodes to a string).
        # `.headers.get(...)` with a default avoids a KeyError if the header is somehow absent.
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        return response.content, content_type

    def send_message(self, chat_id: int, text: str) -> None:
        """
        Send a plain-text message back to a chat (used for "Saved to are.na ✓" confirmations).

        This is best-effort: if the confirmation fails to send, we don't want that to blow up
        the whole webhook (the block was already saved). The caller decides whether to ignore
        errors; here we just raise_for_status and let them wrap it in a try/except if desired.
        """
        response = self._session.post(
            f"{self._api_base}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
