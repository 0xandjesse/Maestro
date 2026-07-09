"""Schema validation for gate engine tokens and gates.

Every token and gate passes through these validators before being stored.
Malformed entries are rejected.
"""

from __future__ import annotations

from typing import Any

from .interface import GateType

# ── valid states ────────────────────────────────────────────────────────

VALID_STATES = frozenset({
    "created",
    "scheduled",
    "released",
    "claimed",
    "completed",
    "expired",
})

TERMINAL_STATES = frozenset({"completed", "expired"})


# ── helpers ─────────────────────────────────────────────────────────────

def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_optional_int(value: Any) -> bool:
    return value is None or isinstance(value, int)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_dict_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, dict) for v in value)


# ── token validation ────────────────────────────────────────────────────

def validate_token(token: dict[str, Any]) -> list[str]:
    """Validate a single token dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(token, dict):
        return ["token is not a dict"]

    # token_id — required
    if not _is_nonempty_str(token.get("token_id")):
        errors.append("token_id must be a non-empty string")

    # state — required, must be valid
    state = token.get("state")
    if not _is_nonempty_str(state):
        errors.append("state must be a non-empty string")
    elif state not in VALID_STATES:
        errors.append(
            f"state must be one of {sorted(VALID_STATES)}, got {state!r}"
        )

    # valid_after — optional int
    va = token.get("valid_after")
    if not _is_optional_int(va):
        errors.append("valid_after must be an integer or None")

    # valid_until — optional int
    vu = token.get("valid_until")
    if not _is_optional_int(vu):
        errors.append("valid_until must be an integer or None")

    # depends_on — optional list[str]
    deps = token.get("depends_on")
    if deps is not None and not _is_str_list(deps):
        errors.append("depends_on must be a list of strings")

    # audit_trail — optional list[dict]
    at = token.get("audit_trail")
    if at is not None and not _is_dict_list(at):
        errors.append("audit_trail must be a list of dicts")

    return errors


def validate_gate(gate: dict[str, Any]) -> list[str]:
    """Validate a single gate dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    if not isinstance(gate, dict):
        return ["gate is not a dict"]

    # gate_id — required
    if not _is_nonempty_str(gate.get("gate_id")):
        errors.append("gate_id must be a non-empty string")

    # gate_type — required, must be valid GateType
    gt = gate.get("gate_type")
    valid_types = {t.value for t in GateType}
    if not _is_nonempty_str(gt):
        errors.append("gate_type must be a non-empty string")
    elif gt not in valid_types:
        errors.append(
            f"gate_type must be one of {sorted(valid_types)}, got {gt!r}"
        )

    # config — required dict
    cfg = gate.get("config")
    if not isinstance(cfg, dict):
        errors.append("config must be a dict")

    # token_id — optional string
    tid = gate.get("token_id")
    if tid is not None and not isinstance(tid, str):
        errors.append("token_id must be a string or None")

    return errors
