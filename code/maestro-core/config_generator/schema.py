# nucleus/modules/config_generator/schema.py
"""Schema validation for AgentConfig objects."""

from __future__ import annotations

from .interface import AgentConfig

# Valid port range (1024–65535, excluding well-known ports)
MIN_PORT = 1024
MAX_PORT = 65535

REQUIRED_FIELDS = [
    "agentId",
    "port",
    "hermesApiUrl",
    "hermesApiKey",
    "conversation",
    "registryPath",
    "version",
    "knownPeers",
    "surfaceToGateway",
    "gatewayBridgeUrl",
]


def validate_config(config: AgentConfig) -> list[str]:
    """Validate an AgentConfig and return a list of issues.

    Checks performed
    ----------------
    * All required fields are present (non-None, non-empty for strings).
    * ``port`` is an integer in the valid range (1024–65535).
    * ``hermesApiUrl`` and ``gatewayBridgeUrl`` look like URLs.
    * ``knownPeers`` is a non-None dict.
    * ``surfaceToGateway`` is a bool.

    Parameters
    ----------
    config : AgentConfig
        The configuration to validate.

    Returns
    -------
    list[str]
        Human-readable issue descriptions. Empty list means valid.
    """
    issues: list[str] = []

    # ── required fields ────────────────────────────────────────────
    for field_name in REQUIRED_FIELDS:
        value = getattr(config, field_name, None)
        if value is None:
            issues.append(f"Missing required field: {field_name}")
        elif isinstance(value, str) and not value.strip():
            issues.append(f"Required field is empty: {field_name}")

    # ── port range ─────────────────────────────────────────────────
    if config.port is not None:
        if not isinstance(config.port, int):
            issues.append(
                f"port must be an integer, got {type(config.port).__name__}"
            )
        elif config.port < MIN_PORT or config.port > MAX_PORT:
            issues.append(
                f"port {config.port} is outside valid range "
                f"({MIN_PORT}–{MAX_PORT})"
            )

    # ── URL validation ─────────────────────────────────────────────
    if config.hermesApiUrl and isinstance(config.hermesApiUrl, str):
        if not (
            config.hermesApiUrl.startswith("http://")
            or config.hermesApiUrl.startswith("https://")
        ):
            issues.append(
                f"hermesApiUrl '{config.hermesApiUrl}' is not a valid URL"
            )

    if config.gatewayBridgeUrl and isinstance(config.gatewayBridgeUrl, str):
        if not (
            config.gatewayBridgeUrl.startswith("http://")
            or config.gatewayBridgeUrl.startswith("https://")
        ):
            issues.append(
                f"gatewayBridgeUrl '{config.gatewayBridgeUrl}' "
                f"is not a valid URL"
            )

    # ── knownPeers type ────────────────────────────────────────────
    if config.knownPeers is not None and not isinstance(
        config.knownPeers, dict
    ):
        issues.append(
            f"knownPeers must be a dict, got "
            f"{type(config.knownPeers).__name__}"
        )

    # ── surfaceToGateway type ──────────────────────────────────────
    if config.surfaceToGateway is not None and not isinstance(
        config.surfaceToGateway, bool
    ):
        issues.append(
            f"surfaceToGateway must be a bool, got "
            f"{type(config.surfaceToGateway).__name__}"
        )

    return issues
