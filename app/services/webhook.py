"""Best-effort outbound webhook delivery.

``deliver`` POSTs a verified claim to a user-registered endpoint, in the format that
endpoint expects. The format is driven by the ``kind`` the user picked when registering
(slack / discord / custom), not guessed from the URL: a native Slack/Discord message, or
our structured JSON for any other app. This is what lets an end user paste a Slack URL
and have it work without any relay.

Best-effort: the call runs off the event loop (the caller wraps it in
``asyncio.to_thread``, like persistence) and any network/HTTP error is returned as a
message rather than raised, so a slow or failing endpoint never disturbs the live
session. stdlib ``urllib`` is used on purpose — no extra HTTP dependency.

When a ``secret`` is given, the body is signed with HMAC-SHA256 and the digest is sent
as ``X-LFC-Signature: sha256=<hex>`` so a custom receiver can authenticate the origin.
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Bound the wait on the receiver so a hung endpoint can't stall the caller thread.
_TIMEOUT_SECONDS = 5

SIGNATURE_HEADER = "X-LFC-Signature"

# Human-readable bits for the Slack/Discord message (the structured JSON keeps the raw
# status). Kept here so the backend owns the message it sends; mirrors the FR labels.
_STATUS_EMOJI = {
    "false": "❌",
    "verified": "✅",
    "uncertain": "❓",
    "unverifiable": "🔍",
}
_STATUS_LABEL = {
    "false": "Faux",
    "verified": "Vérifié",
    "uncertain": "Incertain",
    "unverifiable": "Non vérifiable",
}


def sign(body: bytes, secret: str) -> str:
    """HMAC-SHA256 of the body, formatted as the ``X-LFC-Signature`` value."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _message(claim: dict) -> str:
    """Plain-text summary of a claim, used for the Slack/Discord message body."""
    status = claim.get("status", "")
    emoji = _STATUS_EMOJI.get(status, "•")
    label = _STATUS_LABEL.get(status, status)
    head = f"{emoji} {label} : {claim.get('text', '')}"
    explanation = claim.get("explanation")
    return f"{head}\n{explanation}" if explanation else head


def build_payload(kind: str, claim: dict, session_id: str) -> dict:
    """Pick the payload shape the destination ``kind`` expects.

    Slack and Discord get their native message field; ``custom`` gets our structured
    event, so a custom integration receives the full claim and can parse it.
    """
    if kind == "slack":
        return {"text": _message(claim)}
    if kind == "discord":
        return {"content": _message(claim)}
    return {"event": "claim", "session_id": session_id, "claim": claim}


def deliver(
    url: str, kind: str, claim: dict, session_id: str, secret: str | None = None
) -> str | None:
    """POST ``claim`` to ``url`` in the ``kind`` format; None ok, else an error string.

    Best-effort and synchronous (call via ``asyncio.to_thread``). The error string is
    handed back so the caller can record delivery health; nothing is raised.
    """
    if not url:
        return None
    body = json.dumps(build_payload(kind, claim, session_id)).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = sign(body, secret)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        # We don't act on the response body — just open and close the connection.
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):
            return None
    except (urllib.error.URLError, TimeoutError) as e:
        logger.error("Webhook delivery to %s failed: %s", url, e)
        return str(e)
