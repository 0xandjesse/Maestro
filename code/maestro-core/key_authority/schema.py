"""Schema validation for key storage and revocation lists.

Every key file and revocation list passes through these validators.
Malformed entries are rejected before they touch disk.
"""

from __future__ import annotations

from typing import Any

# ── per-field constraints ──────────────────────────────────────────────


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


# ── key storage validation ─────────────────────────────────────────────


def validate_key_entry(entry: dict[str, Any]) -> list[str]:
    """Validate a single key storage entry.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["key entry is not a dict"]

    # agent_id — required
    if not _is_nonempty_str(entry.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    # public_key — required, must be 64 hex chars (Ed25519)
    pk = entry.get("public_key")
    if not _is_nonempty_str(pk):
        errors.append("public_key must be a non-empty string")
    elif len(pk) != 64 or not all(c in "0123456789abcdef" for c in pk.lower()):
        errors.append("public_key must be 64 hex characters")

    # private_key_encrypted — required
    if not _is_nonempty_str(entry.get("private_key_encrypted")):
        errors.append("private_key_encrypted must be a non-empty string")

    # created_at — required
    if not _is_positive_int(entry.get("created_at")):
        errors.append("created_at must be a non-negative integer")

    # key_id — required
    if not _is_nonempty_str(entry.get("key_id")):
        errors.append("key_id must be a non-empty string")

    return errors


def validate_key_storage(data: Any) -> list[str]:
    """Validate the full key storage payload (a dict of agent_id -> key entry).

    Returns a list of error messages (empty list = valid).
    """
    if not isinstance(data, dict):
        return ["key storage must be a JSON object"]

    errors: list[str] = []

    for agent_id, entry in data.items():
        if not isinstance(agent_id, str):
            errors.append(f"key storage key {agent_id!r} must be a string")
            continue
        rec_errors = validate_key_entry(entry)
        for e in rec_errors:
            errors.append(f"[{agent_id}] {e}")

    return errors


# ── revocation list validation ─────────────────────────────────────────


def validate_revocation_entry(entry: dict[str, Any]) -> list[str]:
    """Validate a single revocation list entry.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["revocation entry is not a dict"]

    if not _is_nonempty_str(entry.get("key_id")):
        errors.append("key_id must be a non-empty string")

    if not _is_nonempty_str(entry.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    if not _is_positive_int(entry.get("revoked_at")):
        errors.append("revoked_at must be a non-negative integer")

    reason = entry.get("reason")
    if reason is not None and not isinstance(reason, str):
        errors.append("reason must be a string or null")

    return errors


def validate_revocation_list(data: Any) -> list[str]:
    """Validate the full revocation list payload (a list of revocation entries).

    Returns a list of error messages (empty list = valid).
    """
    if not isinstance(data, list):
        return ["revocation list must be a JSON array"]

    errors: list[str] = []
    seen: set[str] = set()

    for i, entry in enumerate(data):
        rec_errors = validate_revocation_entry(entry)
        for e in rec_errors:
            errors.append(f"[{i}] {e}")

        key_id = entry.get("key_id") if isinstance(entry, dict) else None
        if isinstance(key_id, str):
            if key_id in seen:
                errors.append(f"[{i}] duplicate key_id {key_id!r}")
            seen.add(key_id)

    return errors
