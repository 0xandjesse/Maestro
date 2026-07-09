"""Schema validation for DM token entries and revocation lists.

Every token file and revocation list passes through these validators.
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


# ── token entry validation ─────────────────────────────────────────────


def validate_token_entry(entry: dict[str, Any]) -> list[str]:
    """Validate a single DM token storage entry.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["token entry is not a dict"]

    # token_id — required
    if not _is_nonempty_str(entry.get("token_id")):
        errors.append("token_id must be a non-empty string")

    # issuer — required
    if not _is_nonempty_str(entry.get("issuer")):
        errors.append("issuer must be a non-empty string")

    # subject — required
    if not _is_nonempty_str(entry.get("subject")):
        errors.append("subject must be a non-empty string")

    # scope — required, must be a list of strings
    scope = entry.get("scope")
    if not _is_str_list(scope):
        errors.append("scope must be a list of strings")
    elif len(scope) == 0:
        errors.append("scope must not be empty")

    # issued_at — required
    if not _is_positive_int(entry.get("issued_at")):
        errors.append("issued_at must be a non-negative integer")

    # expires_at — required
    if not _is_positive_int(entry.get("expires_at")):
        errors.append("expires_at must be a non-negative integer")

    # signature — required, must be 128 hex chars (Ed25519)
    sig = entry.get("signature")
    if not _is_nonempty_str(sig):
        errors.append("signature must be a non-empty string")
    elif len(sig) != 128 or not all(c in "0123456789abcdef" for c in sig.lower()):
        errors.append("signature must be 128 hex characters (Ed25519)")

    # public_key — required, must be 64 hex chars (Ed25519)
    pk = entry.get("public_key")
    if not _is_nonempty_str(pk):
        errors.append("public_key must be a non-empty string")
    elif len(pk) != 64 or not all(c in "0123456789abcdef" for c in pk.lower()):
        errors.append("public_key must be 64 hex characters (Ed25519)")

    return errors


# ── revocation list validation ─────────────────────────────────────────


def validate_revocation_entry(entry: dict[str, Any]) -> list[str]:
    """Validate a single DM token revocation entry.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["revocation entry is not a dict"]

    if not _is_nonempty_str(entry.get("token_id")):
        errors.append("token_id must be a non-empty string")

    if not _is_positive_int(entry.get("revoked_at")):
        errors.append("revoked_at must be a non-negative integer")

    reason = entry.get("reason")
    if reason is not None and not isinstance(reason, str):
        errors.append("reason must be a string or null")

    return errors


def validate_revocation_list(data: Any) -> list[str]:
    """Validate the full DM token revocation list payload.

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

        token_id = entry.get("token_id") if isinstance(entry, dict) else None
        if isinstance(token_id, str):
            if token_id in seen:
                errors.append(f"[{i}] duplicate token_id {token_id!r}")
            seen.add(token_id)

    return errors
