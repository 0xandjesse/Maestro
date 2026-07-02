"""Schema validation for Bridge Surface messages.

Every SurfaceMessage passes through these validators before surfacing.
Malformed messages are rejected before they reach platform adapters.
"""

from __future__ import annotations

from typing import Any

# ── per-field constraints ──────────────────────────────────────────────

VALID_MSG_TYPES = frozenset({"direct", "broadcast", "system"})
VALID_PLATFORMS = frozenset({"telegram", "discord", "p2n"})


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


# ── message-level validation ───────────────────────────────────────────

def validate_surface_message(msg: dict[str, Any]) -> list[str]:
    """Validate a SurfaceMessage dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(msg, dict):
        return ["message is not a dict"]

    # agent_id — required
    if not _is_nonempty_str(msg.get("agent_id")):
        errors.append("agent_id must be a non-empty string")

    # from_agent — required
    if not _is_nonempty_str(msg.get("from_agent")):
        errors.append("from_agent must be a non-empty string")

    # content — required
    if not _is_nonempty_str(msg.get("content")):
        errors.append("content must be a non-empty string")

    # summary — required
    if not _is_nonempty_str(msg.get("summary")):
        errors.append("summary must be a non-empty string")

    # msg_type — required, must be valid
    mt = msg.get("msg_type")
    if not _is_nonempty_str(mt):
        errors.append("msg_type must be a non-empty string")
    elif mt not in VALID_MSG_TYPES:
        errors.append(
            f"msg_type must be one of {sorted(VALID_MSG_TYPES)}, got {mt!r}"
        )

    # platform — required, must be valid
    pf = msg.get("platform")
    if not _is_nonempty_str(pf):
        errors.append("platform must be a non-empty string")
    elif pf not in VALID_PLATFORMS:
        errors.append(
            f"platform must be one of {sorted(VALID_PLATFORMS)}, got {pf!r}"
        )

    return errors
