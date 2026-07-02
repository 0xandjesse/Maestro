"""Agent Lifecycle — schema validators.

Validates AgentSpec and AgentCreateResult data.
"""

from __future__ import annotations

from typing import Any


def validate_agent_spec(data: dict[str, Any]) -> list[str]:
    """Validate an AgentSpec dict.  Returns a list of issues (empty = valid)."""
    issues: list[str] = []

    # Required string fields
    for field in ("agent_id", "display_name", "role", "model", "provider"):
        val = data.get(field)
        if not val or not isinstance(val, str):
            issues.append(f"Missing or invalid required field: {field}")

    # Optional port fields — if present, must be positive ints
    for field in ("transport_port", "gateway_port"):
        val = data.get(field)
        if val is not None:
            if not isinstance(val, int) or val <= 0 or val > 65535:
                issues.append(f"Invalid port value for {field}: {val!r}")

    return issues


def validate_create_result(data: dict[str, Any]) -> list[str]:
    """Validate an AgentCreateResult dict.  Returns a list of issues."""
    issues: list[str] = []

    for field in ("agent_id", "config_path", "systemd_unit"):
        val = data.get(field)
        if not val or not isinstance(val, str):
            issues.append(f"Missing or invalid required field: {field}")

    for field in ("transport_port", "gateway_port"):
        val = data.get(field)
        if not isinstance(val, int) or val <= 0 or val > 65535:
            issues.append(f"Invalid port value for {field}: {val!r}")

    warnings = data.get("warnings")
    if warnings is not None and not isinstance(warnings, list):
        issues.append("warnings must be a list")

    return issues
