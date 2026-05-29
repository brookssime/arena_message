"""
app.py
======

The web server. It does two jobs:

1. POST /telegram  — the webhook Telegram calls whenever you message your bot. We turn each
   message into an are.na block (text -> text block, a URL -> link block, a photo -> image
   block, with the caption stored as the block's description).

2. GET /media/<name> — serves the photos we downloaded from Telegram, at a public URL, so
   that are.na can fetch them. (are.na can't read Telegram's authenticated URLs, so we
   re-host the bytes here. are.na makes its own permanent copy on ingest, so these files only
   need to be reachable for a short window.)

Idiomatic Python / Flask notes for a TS/Kotlin dev:
- Flask uses decorators (`@app.route(...)`) to map URLs to functions. A decorator is a function
  that wraps another function — similar to a TS method decorator or a Kotlin annotation that's
  actually executable. The decorated function runs when a matching request arrives.
- `request` is a global-ish object that Flask fills in per-request (it's thread-local under the
  hood, so it's safe). You read the body via `request.get_json()`, headers via `request.headers`.
- Returning `("text", status_code)` from a view sets the HTTP status. Returning a dict makes
  Flask send JSON automatically.
- `abort(403)` raises an exception that Flask turns into a 403 response — an early-exit guard.
"""

from __future__ import annotations

import logging
import mimetypes
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, request, send_from_directory

from arena_client import ArenaClient
from config import load_config
from telegram_client import TelegramClient

# --- Startup wiring -----------------------------------------------------------------------
# Load + validate configuration once, at import time. If a required secret is missing the app
# refuses to start (fail fast) instead of crashing on the first message.
config = load_config()

# Make sure the directory we save photos into exists. `parents=True` creates intermediate dirs;
# `exist_ok=True` means "don't error if it's already there" (like `mkdir -p`).
config.media_dir.mkdir(parents=True, exist_ok=True)

# Construct our two API clients from config. These are reused across all requests.
arena = ArenaClient(config.arena_access_token, config.arena_channel_slug)
telegram = TelegramClient(config.telegram_bot_token)

# `logging` is the standard library's logger (prefer it over print() for servers — it adds
# timestamps/levels and is configurable). The cloud host captures stdout/stderr as your logs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("arena_message")

# The Flask application object. `__name__` tells Flask where the app lives (for finding files).
app = Flask(__name__)


# --- Small helpers ------------------------------------------------------------------------


def _looks_like_url(text: str) -> bool:
    """
    Heuristic: is this message just a single link (and not a sentence)?

    We treat it as a URL if it parses with an http/https scheme and has no spaces. If so we'll
    send it to are.na as a `source` (link block); otherwise as `content` (text block).
    """
    text = text.strip()
    if " " in text:
        return False
    parsed = urlparse(text)
    # `in (...)` is Python's membership test — like `scheme in ["http","https"]` but on a tuple.
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _save_media(data: bytes, content_type: str) -> str:
    """
    Save downloaded photo bytes to MEDIA_DIR under an UNGUESSABLE filename and return that
    filename. The random name is the security boundary: /media/<name> is public, so the only
    thing stopping a stranger from reading your photos is that they can't guess the name.

    `secrets.token_urlsafe(16)` gives ~128 bits of cryptographically-random, URL-safe text —
    use the `secrets` module (not `random`) for anything security-sensitive.
    """
    # Map the MIME type to a file extension (".jpg", ".png", ...). Fall back to .bin if unknown.
    extension = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    name = f"{secrets.token_urlsafe(16)}{extension}"

    # `with open(...) as f:` is a context manager — it guarantees the file is closed even if an
    # error happens mid-write. This is Python's equivalent of Kotlin's `use { }` / try-with-
    # resources. "wb" = write, binary mode (because we're writing raw bytes, not text).
    with open(config.media_dir / name, "wb") as f:
        f.write(data)
    return name


def _ingest_photo(file_id: str, caption: str | None) -> None:
    """Download a Telegram photo, re-host it, and create an are.na image block from it."""
    data, content_type = telegram.download_file(file_id)
    name = _save_media(data, content_type)

    # The public URL are.na will fetch. config.public_base_url already has any trailing slash
    # stripped, so this builds a clean ".../media/<name>".
    public_url = f"{config.public_base_url}/media/{name}"

    block = arena.create_block(source=public_url)
    log.info("Created image block %s from %s", block.get("id"), public_url)

    # If the user attached a caption, store it as the block's description so it travels along.
    if caption:
        arena.update_block(block["id"], description=caption)


def _ingest_text(text: str) -> None:
    """Create a link block (if the text is a bare URL) or a text block (otherwise)."""
    if _looks_like_url(text):
        block = arena.create_block(source=text)
        log.info("Created link block %s", block.get("id"))
    else:
        block = arena.create_block(content=text)
        log.info("Created text block %s", block.get("id"))


# --- Routes -------------------------------------------------------------------------------


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """
    Handle one incoming Telegram update.

    Security gauntlet, in order, before we touch are.na:
      1. The secret header must match (proves the request is really from our Telegram webhook).
      2. The sender's user id must be on our allowlist (only YOU can post to your channel).
    Only after both pass do we create a block.
    """
    # 1) Verify Telegram's secret-token header. We set this secret when registering the webhook;
    #    Telegram echoes it back on every call. `secrets.compare_digest` is a constant-time
    #    comparison that avoids leaking info via timing — use it for comparing secrets.
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(received_secret, config.telegram_webhook_secret):
        log.warning("Rejected webhook: bad or missing secret token")
        abort(403)

    # Parse the JSON body Telegram sent. `silent=True` returns None instead of raising if the
    # body isn't valid JSON, so we can handle it gracefully.
    update = request.get_json(silent=True) or {}

    # An Update may contain many things; we only care about plain `message`s. `.get` chains
    # safely return None instead of throwing if a key is absent (no optional-chaining `?.` in
    # Python, so we lean on dict.get defaults).
    message = update.get("message")
    if not message:
        # Not a message we handle (could be an edited message, a reaction, etc.). Acknowledge
        # with 200 so Telegram doesn't retry forever.
        return ("", 200)

    # 2) Allowlist the sender by numeric user id.
    sender_id = (message.get("from") or {}).get("id")
    if sender_id is None:
        # First-run convenience: if you haven't set your id yet, this log line tells you what
        # to put in ALLOWED_TELEGRAM_USER_ID.
        log.info("Message had no sender id; full message: %s", message)
        abort(403)
    if sender_id != config.allowed_telegram_user_id:
        log.warning("Rejected message from non-allowlisted user id %s", sender_id)
        abort(403)

    # --- Dispatch on message type -------------------------------------------------------
    chat_id = message["chat"]["id"]
    caption = message.get("caption")  # photos/documents can carry a caption

    try:
        if message.get("photo"):
            # `photo` is a list of the same image at increasing resolutions. The LAST entry is
            # the largest. `[-1]` indexes from the end — a handy Python idiom.
            largest = message["photo"][-1]
            _ingest_photo(largest["file_id"], caption)

        elif message.get("document") and str(
            (message["document"].get("mime_type") or "")
        ).startswith("image/"):
            # Photos sent as a *file* ("uncompressed") arrive as a document with an image mime.
            _ingest_photo(message["document"]["file_id"], caption)

        elif message.get("text"):
            _ingest_text(message["text"])

        else:
            # Something we don't handle yet (sticker, voice note, location, ...).
            telegram.send_message(
                chat_id, "Sorry, I can only save text, links, and photos."
            )
            return ("", 200)

        # Best-effort confirmation. If sending the reply fails, we've still saved the block, so
        # we swallow that particular error rather than returning a 500 (which Telegram retries).
        try:
            telegram.send_message(chat_id, "Saved to are.na ✓")
        except Exception:  # noqa: BLE001 - intentional best-effort
            log.exception("Failed to send confirmation reply (block was still saved)")

    except Exception:
        # Log the full traceback for debugging. Returning 200 anyway is a deliberate choice:
        # we don't want Telegram to redeliver the same failing message in a tight retry loop.
        # (For a first project this is the friendly default; you could return 500 to force
        # retries once things are stable.)
        log.exception("Failed to handle message")
        try:
            telegram.send_message(
                chat_id, "Something went wrong saving that. Check the logs."
            )
        except Exception:  # noqa: BLE001
            pass

    return ("", 200)


@app.route("/media/<path:name>", methods=["GET"])
def serve_media(name: str):
    """
    Serve a re-hosted photo so are.na can fetch it.

    `send_from_directory` is the safe way to serve user-referenced filenames: it refuses paths
    that try to escape the directory (e.g. "../../etc/passwd"), so we don't have to hand-roll
    path-traversal defenses. The unguessable filename is what keeps these private.
    """
    return send_from_directory(config.media_dir, name)


@app.route("/health", methods=["GET"])
def health():
    """A trivial endpoint so the host (and you) can check the server is alive."""
    return {"status": "ok"}


# The `if __name__ == "__main__":` guard means "only run this when the file is executed
# directly (python app.py), NOT when it's imported." In production, gunicorn imports `app`
# instead, so this block is skipped. It's Python's equivalent of a `fun main()` entry point.
if __name__ == "__main__":
    # Flask's built-in server is for LOCAL DEV ONLY. In production we run gunicorn (see Dockerfile).
    app.run(host="0.0.0.0", port=config.port)
