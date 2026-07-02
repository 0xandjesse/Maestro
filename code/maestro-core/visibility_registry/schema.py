"""Schema validation for visibility registry records.

Every write to the visibility registry passes through these validators.
Malformed entries are rejected before they touch disk.
"""

from __future__ import annotations

from typing import Any

# ── per-field constraints ──────────────────────────────────────────────

VALID_MODES = frozenset({"long", "short", "off"})
VALID_DIRECTIONS = frozenset({"inbound", "outbound"})


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


# ── record-level validation ────────────────────────────────────────────

def validate_config(entry: dict[str, Any]) -> list[str]:
    """Validate a single visibility config dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(entry, dict):
        return ["entry is not a dict"]

    # agent_id — required
    if not _is_nonempty_str(entry.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    # display_mode — required, must be valid
    mode = entry.get("display_mode")
    if not _is_nonempty_str(mode):
        errors.append("display_mode must be a non-empty string")
    elif mode not in VALID_MODES:
        errors.append(
            f"display_mode must be one of {sorted(VALID_MODES)}, got {mode!r}"
        )

    # surface_inbound — optional, must be bool if present
    si = entry.get("surface_inbound")
    if si is not None and not _is_bool(si):
        errors.append("surface_inbound must be a boolean")

    # surface_outbound — optional, must be bool if present
    so = entry.get("surface_outbound")
    if so is not None and not _is_bool(so):
        errors.append("surface_outbound must be a boolean")

    # surface_system — optional, must be bool if present
    ss = entry.get("surface_system")
    if ss is not None and not _is_bool(ss):
        errors.append("surface_system must be a boolean")

    # generated_at — optional, must be int >= 0 if present
    ga = entry.get("generated_at")
    if ga is not None and not _is_positive_int(ga):
        errors.append("generated_at must be a non-negative integer")

    return errors


def validate_registry(data: Any) -> list[str]:
    """Validate the full visibility registry payload (a list of records).

    Returns a list of error messages (empty list = valid).
    """
    if not isinstance(data, list):
        return ["visibility registry must be a JSON array"]

    errors: list[str] = []
    seen: set[str] = set()

    for i, entry in enumerate(data):
        rec_errors = validate_config(entry)
        for e in rec_errors:
            errors.append(f"[{i}] {e}")

        agent_id = entry.get("agent_id") if isinstance(entry, dict) else None
        if isinstance(agent_id, str):
            if agent_id in seen:
                errors.append(f"[{i}] duplicate agent_id {agent_id!r}")
            seen.add(agent_id)

    return errors
