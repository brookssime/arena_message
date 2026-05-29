"""
scripts/test_arena.py
=====================

A quick standalone check that your are.na token + channel slug work, WITHOUT needing Telegram
or a public server. It creates a single text block in your channel, then prints it so you can
confirm it shows up at https://www.are.na/brooks-sime/staging-y7mhkxq-1mw.

Usage (from the project root, with your .env populated):
    python scripts/test_arena.py

This is the cheapest way to isolate "is my are.na setup correct?" from "is my server correct?".
Delete the test block from the are.na web UI afterward (or leave it — it's harmless).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena_client import ArenaClient  # noqa: E402
from config import load_config  # noqa: E402


def main() -> None:
    config = load_config()
    arena = ArenaClient(config.arena_access_token, config.arena_channel_slug)

    block = arena.create_block(content="✅ test block from arena_message setup")
    # f-strings (the f"..." prefix) interpolate expressions in {braces} — like JS template
    # literals. `block.get("id")` reads a key, returning None instead of throwing if absent.
    print(f"Created block id={block.get('id')} class={block.get('class')}")
    print("Check your channel: https://www.are.na/brooks-sime/staging-y7mhkxq-1mw")


if __name__ == "__main__":
    main()
