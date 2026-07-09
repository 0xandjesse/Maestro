"""Registry Manager — Interface Contract.

Defines AgentRecord (the canonical agent representation) and the
RegistryManager abstract base class that all implementations must satisfy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentRecord:
    """Canonical agent record stored in the registry.

    All fields use camelCase to match the on-disk JSON format consumed
    by the existing Maestro transport layer and JS LocalRegistry.
    """

    agentId: str
    webhookEndpoint: str
    capabilities: list[str] = field(default_factory=list)
    registeredAt: int = 0
    lastSeen: int = 0
    status: str = "active"
    publicKey: str | None = None


class RegistryManager(ABC):
    """Abstract interface for the agent registry.

    Implementations must provide single-writer safety, schema validation,
    and atomic writes.  The default implementation lives in manager.py.
    """

    @abstractmethod
    def lookup(self, agent_id: str) -> AgentRecord | None:
        """Return the record for *agent_id*, or None if not found."""
        ...

    @abstractmethod
    def register(
        self,
        agent_id: str,
        webhook_endpoint: str,
        capabilities: list[str] | None = None,
    ) -> AgentRecord:
        """Create or update an agent record.  Returns the stored record."""
        ...

    @abstractmethod
    def unregister(self, agent_id: str) -> bool:
        """Remove *agent_id* from the registry.  Returns True if it existed."""
        ...

    @abstractmethod
    def list_all(self) -> list[AgentRecord]:
        """Return every agent currently in the registry."""
        ...

    @abstractmethod
    def update_last_seen(self, agent_id: str) -> bool:
        """Bump the lastSeen timestamp for *agent_id*.  Returns True on success."""
        ...

    @abstractmethod
    def set_status(self, agent_id: str, status: str) -> bool:
        """Set the status field for *agent_id*.  Returns True on success."""
        ...
