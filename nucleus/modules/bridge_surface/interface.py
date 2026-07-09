"""Bridge Surface — Interface Contract.

Defines SurfaceMessage, SurfaceResult, and the BridgeSurface abstract
base class that all implementations must satisfy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SurfaceMessage:
    """A message to be surfaced to a platform."""

    agent_id: str
    from_agent: str
    content: str
    summary: str
    msg_type: str                    # "direct", "broadcast", "system"
    platform: str = "telegram"       # "telegram", "discord", "p2n"


@dataclass
class SurfaceResult:
    """Result of a surface operation."""

    ok: bool
    displayed: bool
    platform: str
    message_id: str | None = None
    detail: str | None = None


class BridgeSurface(ABC):
    """Abstract interface for the bridge surface.

    Implementations must route messages to platform adapters,
    check visibility before surfacing, and manage display modes
    via the Visibility Registry.
    """

    @abstractmethod
    def surface(self, message: SurfaceMessage) -> SurfaceResult:
        """Route *message* to the appropriate platform for display.

        Checks visibility before surfacing.  Returns a SurfaceResult
        indicating whether the message was displayed.
        """
        ...

    @abstractmethod
    def get_display_mode(self, agent_id: str) -> str:
        """Query the visibility registry for *agent_id*'s display mode.

        Returns one of ``"on"`` or ``"off"``.
        """
        ...

    @abstractmethod
    def set_display_mode(self, agent_id: str, mode: str) -> bool:
        """Update *agent_id*'s display mode in the visibility registry.

        Returns True if the update succeeded.
        """
        ...
