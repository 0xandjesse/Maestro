"""Schema validation for session checkpoint records.

Every checkpoint written to disk passes through these validators.
Malformed entries are rejected before they touch disk.
"""

from __future__ import annotations

from typing import Any


# ── per-field constraints ──────────────────────────────────────────────


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_str_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _is_list_of_str(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


# ── record-level validation ────────────────────────────────────────────


def validate_state(entry: dict[str, Any]) -> list[str]:
    """Validate a single SessionState dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["entry is not a dict"]

    # agent_id — required
    if not _is_nonempty_str(entry.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    # session_id — required
    if not _is_nonempty_str(entry.get("session_id")):
        errors.append("session_id must be a non-empty string")

    # active_tasks — required, must be list of strings
    tasks = entry.get("active_tasks")
    if tasks is None:
        errors.append("active_tasks is required")
    elif not _is_list_of_str(tasks):
        errors.append("active_tasks must be a list of strings")

    # context_summary — required, must be string
    summary = entry.get("context_summary")
    if not isinstance(summary, str):
        errors.append("context_summary must be a string")

    # last_message_id — optional, string or None
    lmi = entry.get("last_message_id")
    if not _is_str_or_none(lmi):
        errors.append("last_message_id must be a string or null")

    # checkpointed_at — required, int >= 0
    ca = entry.get("checkpointed_at")
    if not _is_positive_int(ca):
        errors.append("checkpointed_at must be a non-negative integer")

    # version — required, int >= 0
    ver = entry.get("version")
    if not _is_positive_int(ver):
        errors.append("version must be a non-negative integer")

    return errors
