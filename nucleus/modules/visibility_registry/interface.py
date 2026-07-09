"""Visibility Registry — Interface Contract.

Defines VisibilityConfig (the canonical visibility representation) and the
VisibilityRegistry abstract base class that all implementations must satisfy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VisibilityConfig:
    """Per-agent visibility configuration.

    All fields use snake_case to match the on-disk JSON format.
    """

    agent_id: str
    display_mode: str  # "on" | "off"
    surface_inbound: bool = True
    surface_outbound: bool = True
    surface_system: bool = False
    generated_at: int = 0


class VisibilityRegistry(ABC):
    """Abstract interface for the visibility registry.

    Implementations must provide per-agent visibility checks, mode
    switching, default generation, and full listing.
    """

    @abstractmethod
    def check(self, agent_id: str, direction: str) -> tuple[bool, str]:
        """Return (visible, mode) for *agent_id* in *direction*.

        *direction* must be "inbound" or "outbound".
        """
        ...

    @abstractmethod
    def set_mode(self, agent_id: str, mode: str) -> VisibilityConfig:
        """Set the display mode for *agent_id*.  Returns the updated config."""
        ...

    @abstractmethod
    def generate_for_agent(self, agent_id: str) -> VisibilityConfig:
        """Generate (or return existing) default config for *agent_id*."""
        ...

    @abstractmethod
    def list_all(self) -> list[VisibilityConfig]:
        """Return every visibility config currently stored."""
        ...
