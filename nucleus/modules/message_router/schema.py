"""Schema validation for message envelopes.

Every message passes through these validators before routing.
Malformed messages are rejected.
"""

from __future__ import annotations

from typing import Any

from .interface import MessageEnvelope


# ── per-field constraints ──────────────────────────────────────────────


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


# ── message validation ─────────────────────────────────────────────────


def validate_message(message: MessageEnvelope) -> list[str]:
    """Validate a MessageEnvelope's required fields.

    Returns a list of error messages (empty list = valid).

    Required fields: id, type, sender, recipient, content, timestamp.
    """
    errors: list[str] = []

    # id — required, non-empty string
    if not _is_nonempty_str(message.id):
        errors.append("id must be a non-empty string")

    # type — required, must be one of the valid types
    valid_types = {"direct", "broadcast", "proxy", "system"}
    if not _is_nonempty_str(message.type):
        errors.append("type must be a non-empty string")
    elif message.type not in valid_types:
        errors.append(
            f"type {message.type!r} is not valid "
            f"(valid: {sorted(valid_types)})"
        )

    # sender — required, must be a dict with agentId
    if not _is_dict(message.sender):
        errors.append("sender must be a dict")
    elif "agentId" not in message.sender or not _is_nonempty_str(message.sender.get("agentId")):
        errors.append("sender must contain a non-empty 'agentId' field")

    # recipient — required, must be a dict with agentId
    if not _is_dict(message.recipient):
        errors.append("recipient must be a dict")
    elif "agentId" not in message.recipient or not _is_nonempty_str(message.recipient.get("agentId")):
        errors.append("recipient must contain a non-empty 'agentId' field")

    # content — required, non-empty string
    if not _is_nonempty_str(message.content):
        errors.append("content must be a non-empty string")

    # timestamp — required, positive int
    if not _is_positive_int(message.timestamp):
        errors.append("timestamp must be a non-negative integer")

    # version — required, non-empty string
    if not _is_nonempty_str(message.version):
        errors.append("version must be a non-empty string")

    # intent — optional, but if present must be a valid intent string
    if message.intent is not None:
        valid_intents = {"work", "ack", "query", "status", "system", "unknown"}
        if not isinstance(message.intent, str):
            errors.append("intent must be a string or None")
        elif message.intent not in valid_intents:
            errors.append(
                f"intent {message.intent!r} is not valid "
                f"(valid: {sorted(valid_intents)})"
            )

    # inReplyTo — optional, but if present must be str
    if message.inReplyTo is not None and not isinstance(message.inReplyTo, str):
        errors.append("inReplyTo must be a string or None")

    # stageId — optional, but if present must be str
    if message.stageId is not None and not isinstance(message.stageId, str):
        errors.append("stageId must be a string or None")

    # venueId — optional, but if present must be str
    if message.venueId is not None and not isinstance(message.venueId, str):
        errors.append("venueId must be a string or None")

    # ttl — optional, but if present must be int
    if message.ttl is not None and not isinstance(message.ttl, int):
        errors.append("ttl must be an integer or None")

    return errors
