# Module 16: Transport State Refresh — Schema
# Signal type constants and validation.

from enum import StrEnum


class SignalType(StrEnum):
    """Valid signal types for transport state refresh."""

    SIGHUP = "SIGHUP"
    REFRESH = "REFRESH"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    TOKEN_UPDATE = "TOKEN_UPDATE"


VALID_SIGNAL_TYPES: frozenset[str] = frozenset(SignalType)

# Default configs and tokens that get reloaded on refresh
DEFAULT_CONFIGS: list[str] = [
    "transport.yaml",
    "gateway.yaml",
    "routing.yaml",
]

DEFAULT_TOKENS: list[str] = [
    "dm_token",
    "session_token",
]
