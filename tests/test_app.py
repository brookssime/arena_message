"""
tests/test_app.py
================

End-to-end-ish tests of the Flask webhook using Flask's test client (no real network). These
cover the security gauntlet, message-type routing, caption handling, media re-hosting, and the
/media serving route (including path-traversal safety).
"""

import os

from conftest import ALLOWED_USER_ID, WEBHOOK_SECRET

# Header dict with the correct secret, reused across tests.
GOOD_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}


def _message(**fields):
    """Helper to build a Telegram `message` with sensible defaults for sender + chat."""
    fields.setdefault("from", {"id": ALLOWED_USER_ID})
    fields.setdefault("chat", {"id": 7})
    return {"message": fields}


# --- security gauntlet --------------------------------------------------------------------

def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_missing_secret_is_rejected(client):
    response = client.post("/telegram", json=_message(text="hi"))
    assert response.status_code == 403


def test_wrong_secret_is_rejected(client):
    response = client.post(
        "/telegram", json=_message(text="hi"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
    )
    assert response.status_code == 403


def test_non_allowlisted_sender_is_rejected(client, fakes):
    response = client.post(
        "/telegram",
        json={"message": {"from": {"id": 999}, "chat": {"id": 1}, "text": "hi"}},
        headers=GOOD_HEADERS,
    )
    assert response.status_code == 403
    # Crucially, nothing was written to are.na.
    assert fakes.arena.calls == []


def test_non_message_update_is_acked_without_side_effects(client, fakes):
    # e.g. an edited message — we acknowledge with 200 but do nothing.
    response = client.post("/telegram", json={"edited_message": {"text": "x"}}, headers=GOOD_HEADERS)
    assert response.status_code == 200
    assert fakes.arena.calls == []


# --- routing ------------------------------------------------------------------------------

def test_plain_text_creates_text_block(client, fakes):
    client.post("/telegram", json=_message(text="just a thought"), headers=GOOD_HEADERS)
    assert ("create", None, "just a thought") in fakes.arena.calls


def test_bare_url_creates_link_block(client, fakes):
    client.post("/telegram", json=_message(text="https://are.na/page"), headers=GOOD_HEADERS)
    # A bare URL goes in as `source`, not `content`.
    assert ("create", "https://are.na/page", None) in fakes.arena.calls


def test_photo_creates_image_block_with_rehosted_url_and_caption(client, fakes):
    client.post(
        "/telegram",
        json=_message(photo=[{"file_id": "small"}, {"file_id": "big"}], caption="my cat"),
        headers=GOOD_HEADERS,
    )

    # The create call's source must be our re-hosted /media URL (NOT a telegram.org URL).
    create_calls = [c for c in fakes.arena.calls if c[0] == "create"]
    assert len(create_calls) == 1
    source = create_calls[0][1]
    assert source.startswith("https://example.test/media/")
    assert source.endswith(".jpg")
    assert "telegram.org" not in source

    # The caption was attached as the block's description.
    assert ("update", 555, None, "my cat") in fakes.arena.calls

    # And the bytes were actually written into the (temp) media dir.
    saved = [f for f in os.listdir(fakes.media_dir) if f.endswith(".jpg")]
    assert len(saved) == 1


def test_photo_without_caption_does_not_call_update(client, fakes):
    client.post(
        "/telegram",
        json=_message(photo=[{"file_id": "big"}]),
        headers=GOOD_HEADERS,
    )
    assert not any(c[0] == "update" for c in fakes.arena.calls)


def test_image_document_is_treated_like_a_photo(client, fakes):
    client.post(
        "/telegram",
        json=_message(document={"file_id": "doc1", "mime_type": "image/png"}),
        headers=GOOD_HEADERS,
    )
    create_calls = [c for c in fakes.arena.calls if c[0] == "create"]
    assert len(create_calls) == 1
    assert create_calls[0][1].startswith("https://example.test/media/")


def test_unsupported_type_replies_and_creates_nothing(client, fakes):
    # A sticker (no text/photo/document) should get a polite reply and no are.na write.
    client.post("/telegram", json=_message(sticker={"file_id": "s"}), headers=GOOD_HEADERS)
    assert fakes.arena.calls == []
    assert any("can only save" in text for _, text in fakes.telegram.replies)


def test_successful_save_sends_confirmation(client, fakes):
    client.post("/telegram", json=_message(text="hello"), headers=GOOD_HEADERS)
    assert any("Saved to are.na" in text for _, text in fakes.telegram.replies)


# --- media serving ------------------------------------------------------------------------

def test_media_route_serves_saved_file(client, fakes):
    # First post a photo so a file exists, then fetch it back through /media.
    client.post("/telegram", json=_message(photo=[{"file_id": "big"}]), headers=GOOD_HEADERS)
    name = os.listdir(fakes.media_dir)[0]

    response = client.get(f"/media/{name}")
    assert response.status_code == 200
    assert response.data == b"\xff\xd8\xff fake-jpeg-bytes"


def test_media_route_blocks_path_traversal(client, fakes):
    # Attempting to escape the media dir must not return a sensitive file.
    response = client.get("/media/..%2f..%2fconfig.py")
    assert response.status_code in (403, 404)
