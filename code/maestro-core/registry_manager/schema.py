"""Schema validation for agent registry records.

Every write to the registry passes through these validators.  Malformed
entries are rejected before they touch disk.
"""

from __future__ import annotations

from typing import Any

# ── per-field constraints ──────────────────────────────────────────────

VALID_STATUSES = frozenset({"active", "inactive", "suspended", "error"})


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_optional_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


# ── record-level validation ────────────────────────────────────────────

def validate_record(entry: dict[str, Any]) -> list[str]:
    """Validate a single agent record dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["entry is not a dict"]

    # agentId — required
    if not _is_nonempty_str(entry.get("agentId")):
        errors.append("agentId must be a non-empty string")

    # webhookEndpoint — required
    if not _is_nonempty_str(entry.get("webhookEndpoint")):
        errors.append("webhookEndpoint must be a non-empty string")

    # capabilities — optional, must be list[str] if present
    caps = entry.get("capabilities")
    if caps is not None and not _is_str_list(caps):
        errors.append("capabilities must be a list of strings")

    # registeredAt — optional, must be int >= 0 if present
    ra = entry.get("registeredAt")
    if ra is not None and not _is_positive_int(ra):
        errors.append("registeredAt must be a non-negative integer")

    # lastSeen — optional, must be int >= 0 if present
    ls = entry.get("lastSeen")
    if ls is not None and not _is_positive_int(ls):
        errors.append("lastSeen must be a non-negative integer")

    # status — optional, must be valid if present
    st = entry.get("status")
    if st is not None and st not in VALID_STATUSES:
        errors.append(
            f"status must be one of {sorted(VALID_STATUSES)}, got {st!r}"
        )

    # publicKey — optional, must be str | None if present
    pk = entry.get("publicKey")
    if pk is not None and not _is_optional_str(pk):
        errors.append("publicKey must be a string or null")

    return errors


def validate_registry(data: Any) -> list[str]:
    """Validate the full registry payload (a list of records).

    Returns a list of error messages (empty list = valid).
    """
    if not isinstance(data, list):
        return ["registry must be a JSON array"]

    errors: list[str] = []
    seen: set[str] = set()

    for i, entry in enumerate(data):
        rec_errors = validate_record(entry)
        for e in rec_errors:
            errors.append(f"[{i}] {e}")

        agent_id = entry.get("agentId") if isinstance(entry, dict) else None
        if isinstance(agent_id, str):
            if agent_id in seen:
                errors.append(f"[{i}] duplicate agentId {agent_id!r}")
            seen.add(agent_id)

    return errors
