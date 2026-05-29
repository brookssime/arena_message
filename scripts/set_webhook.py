"""
scripts/set_webhook.py
======================

Run this ONCE (and again any time your public URL changes) to tell Telegram where to deliver
your bot's messages. It registers:
  - the webhook URL:  <PUBLIC_BASE_URL>/telegram
  - a secret token:   <TELEGRAM_WEBHOOK_SECRET>  (Telegram echoes this back on every call so
                      our server can verify the request really came from Telegram)

Usage (from the project root, with your .env populated or env vars exported):
    python scripts/set_webhook.py

To inspect the current webhook registration instead, pass `info`:
    python scripts/set_webhook.py info

Idiomatic Python notes:
- `sys.argv` is the list of command-line arguments (argv[0] is the script name itself).
- We import from the project's `config.py`. Because this file lives in a `scripts/` subfolder,
  we add the project root to `sys.path` so the import resolves whether you run it from the root
  or from inside scripts/.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable (one directory up from this scripts/ folder).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402 - must come after the sys.path tweak above

from config import load_config  # noqa: E402


def main() -> None:
    config = load_config()
    api_base = f"https://api.telegram.org/bot{config.telegram_bot_token}"

    # If the user typed `info`, just show the current webhook status and exit.
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        response = requests.get(f"{api_base}/getWebhookInfo", timeout=30)
        print(response.json())
        return

    webhook_url = f"{config.public_base_url}/telegram"
    response = requests.post(
        f"{api_base}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": config.telegram_webhook_secret,
            # Only send us the update types we actually handle, to cut noise.
            "allowed_updates": ["message"],
        },
        timeout=30,
    )
    response.raise_for_status()
    print(f"setWebhook -> {webhook_url}")
    print(response.json())


if __name__ == "__main__":
    main()
