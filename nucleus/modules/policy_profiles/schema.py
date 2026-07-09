"""Policy Profiles — schema validation.

Validates policy profile store data before it touches disk.
"""

from __future__ import annotations

from typing import Any

VALID_PROFILE_KEYS = frozenset({
    "require_signatures",
    "accept_tokens",
    "provenance_required",
    "escrow_participation",
    "relay_authenticated",
    "log_to_audit",
})


def validate_profile_store(data: Any) -> list[str]:
    """Validate a list of policy profile dicts.

    Returns a list of error messages (empty list = valid).
    """
    if not isinstance(data, list):
        return ["profile store must be a JSON array"]

    errors: list[str] = []
    seen_names: set[str] = set()

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            errors.append(f"[{i}] entry is not a dict")
            continue

        # name — required, non-empty string
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"[{i}] name must be a non-empty string")
        else:
            if name in seen_names:
                errors.append(f"[{i}] duplicate profile name {name!r}")
            seen_names.add(name)

        # policies — required, must be a dict
        policies = entry.get("policies")
        if not isinstance(policies, dict):
            errors.append(f"[{i}] policies must be a dict")
        else:
            for key in policies:
                if key not in VALID_PROFILE_KEYS:
                    errors.append(
                        f"[{i}] unknown policy key {key!r}"
                    )

        # description — optional, must be string if present
        desc = entry.get("description")
        if desc is not None and not isinstance(desc, str):
            errors.append(f"[{i}] description must be a string")

    return errors
