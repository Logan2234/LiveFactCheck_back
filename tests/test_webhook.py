"""Tests for best-effort webhook delivery (services/webhook.py).

``deliver`` formats the payload for the destination ``kind`` the user chose (native
Slack/Discord message, or our structured JSON for ``custom``), optionally HMAC-signs it,
and must never raise: a network failure is returned as an error string. ``urlopen`` is
patched — no real call.
"""

import hashlib
import hmac
import json
import urllib.error
from unittest.mock import patch

from app.services import webhook


def _claim(status: str = "false") -> dict:
    return {
        "id": "c1",
        "status": status,
        "text": "La Terre est plate",
        "explanation": "La Terre est un géoïde.",
    }


# --- build_payload: per-kind shape ----------------------------------------------


def test_build_payload_slack_uses_text_field() -> None:
    payload = webhook.build_payload("slack", _claim(), "sess-1")
    assert set(payload) == {"text"}
    assert "La Terre est plate" in payload["text"]


def test_build_payload_discord_uses_content_field() -> None:
    payload = webhook.build_payload("discord", _claim(), "sess-1")
    assert set(payload) == {"content"}
    assert "La Terre est plate" in payload["content"]


def test_build_payload_custom_is_structured() -> None:
    payload = webhook.build_payload("custom", _claim(), "sess-1")
    assert payload == {"event": "claim", "session_id": "sess-1", "claim": _claim()}


# --- deliver --------------------------------------------------------------------


def test_deliver_posts_structured_payload_for_custom() -> None:
    with patch("app.services.webhook.urllib.request.urlopen") as urlopen:
        error = webhook.deliver("https://my-app.test/hook", "custom", _claim(), "s1")

    assert error is None
    request = urlopen.call_args.args[0]
    assert request.method == "POST"
    assert json.loads(request.data) == {
        "event": "claim",
        "session_id": "s1",
        "claim": _claim(),
    }


def test_deliver_posts_slack_message_for_slack_kind() -> None:
    # The URL host is irrelevant now — only the kind decides the format.
    with patch("app.services.webhook.urllib.request.urlopen") as urlopen:
        webhook.deliver("https://example.test/anything", "slack", _claim(), "s")
    body = json.loads(urlopen.call_args.args[0].data)
    assert "text" in body and "claim" not in body


def test_deliver_signs_body_when_secret_given() -> None:
    secret = "s3cr3t"
    with patch("app.services.webhook.urllib.request.urlopen") as urlopen:
        webhook.deliver(
            "https://my-app.test/hook", "custom", _claim(), "s", secret=secret
        )

    request = urlopen.call_args.args[0]
    signature = request.get_header(webhook.SIGNATURE_HEADER.capitalize())
    expected = hmac.new(
        secret.encode("utf-8"), request.data, hashlib.sha256
    ).hexdigest()
    assert signature == f"sha256={expected}"


def test_deliver_noop_without_url() -> None:
    with patch("app.services.webhook.urllib.request.urlopen") as urlopen:
        assert webhook.deliver("", "custom", _claim(), "s") is None
    urlopen.assert_not_called()


def test_deliver_returns_error_on_failure() -> None:
    with patch(
        "app.services.webhook.urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        error = webhook.deliver("https://my-app.test/hook", "custom", _claim(), "s")
    assert error is not None
    assert "connection refused" in error
